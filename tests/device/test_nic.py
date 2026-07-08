"""Tests for NIC device XML generation and validation."""
from __future__ import annotations

import pytest
from xml.etree import ElementTree as ET

from truenas_pylibvirt.device import NICDevice, NICDeviceType, NICDeviceModel, PciAddress
from truenas_pylibvirt.domain.start_validator import pci_slot_error_for_machine


@pytest.mark.parametrize("type_,source,model,mac,trust_guest,expected_xml", [
    (
        NICDeviceType.BRIDGE,
        "br0",
        NICDeviceModel.VIRTIO,
        "00:a0:99:7e:bb:8a",
        False,
        '<interface type="bridge">'
        '<source bridge="br0" />'
        '<model type="virtio" />'
        '<mac address="00:a0:99:7e:bb:8a" />'
        '</interface>'
    ),
    (
        NICDeviceType.DIRECT,
        "ens3",
        NICDeviceModel.VIRTIO,
        "00:a0:99:7e:bb:8a",
        False,
        '<interface type="direct" trustGuestRxFilters="no">'
        '<source dev="ens3" mode="bridge" />'
        '<model type="virtio" />'
        '<mac address="00:a0:99:7e:bb:8a" />'
        '</interface>'
    ),
    (
        NICDeviceType.DIRECT,
        "ens3",
        NICDeviceModel.VIRTIO,
        "00:a0:99:7e:bb:8a",
        True,
        '<interface type="direct" trustGuestRxFilters="yes">'
        '<source dev="ens3" mode="bridge" />'
        '<model type="virtio" />'
        '<mac address="00:a0:99:7e:bb:8a" />'
        '</interface>'
    ),
    (
        NICDeviceType.BRIDGE,
        "br1",
        NICDeviceModel.E1000,
        "00:11:22:33:44:55",
        False,
        '<interface type="bridge">'
        '<source bridge="br1" />'
        '<model type="e1000" />'
        '<mac address="00:11:22:33:44:55" />'
        '</interface>'
    ),
])
def test_nic_xml_generation(type_, source, model, mac, trust_guest, expected_xml, device_context, mock_device_delegate):
    """Test NIC device XML generation for various configurations."""
    device = NICDevice(
        type_=type_,
        source=source,
        model=model,
        mac=mac,
        trust_guest_rx_filters=trust_guest,
        device_delegate=mock_device_delegate
    )

    xml_elements = device.xml(device_context)
    xml_str = ''.join(ET.tostring(elem, encoding='unicode') for elem in xml_elements).strip()

    assert xml_str == expected_xml


def test_nic_identity(mock_device_delegate):
    """Test NIC device identity returns the source interface."""
    device = NICDevice(
        type_=NICDeviceType.BRIDGE,
        source="br0",
        model=NICDeviceModel.VIRTIO,
        mac="00:a0:99:7e:bb:8a",
        trust_guest_rx_filters=False,
        device_delegate=mock_device_delegate
    )

    assert device.identity() == "br0"


@pytest.mark.parametrize("mac,expected_error", [
    ("00:a0:99:7e:bb:8a", None),  # Valid MAC
    ("ff:a0:99:7e:bb:8a", "MAC address must not start with"),  # Invalid - starts with ff
    ("10-66-6a-1f-f1-b1", "MAC address must be a colon-separated"),  # Invalid - dash separators
    ("10-66-6A-1F-F1-B1", "MAC address must be a colon-separated"),  # Invalid - dash separators, uppercase
    ("00a0997ebb8a", "MAC address must be a colon-separated"),  # Invalid - no separators
    ("00:a0:99:7e:bb", "MAC address must be a colon-separated"),  # Invalid - too short
    ("gg:gg:gg:gg:gg:gg", "MAC address must be a colon-separated"),  # Invalid - non-hex digits
])
def test_nic_mac_validation(mac, expected_error, mock_device_delegate):
    """Test NIC MAC address validation."""
    device = NICDevice(
        type_=NICDeviceType.BRIDGE,
        source="br0",
        model=NICDeviceModel.VIRTIO,
        mac=mac,
        trust_guest_rx_filters=False,
        device_delegate=mock_device_delegate
    )

    errors = device.validate()

    if expected_error:
        assert len(errors) > 0
        assert any(expected_error in error[1] for error in errors)
    else:
        # May have other validation errors from delegate, but not MAC errors
        assert not any('mac' in error[0].lower() for error in errors)


@pytest.mark.parametrize("type_,source,model,mac,trust_guest,expected_error", [
    # Valid configuration
    (
        NICDeviceType.BRIDGE,
        "br0",
        NICDeviceModel.VIRTIO,
        "00:a0:99:7e:bb:8a",
        False,
        None
    ),
    # Invalid - trust_guest_rx_filters with bridge device
    (
        NICDeviceType.BRIDGE,
        "br0",
        NICDeviceModel.VIRTIO,
        "00:a0:99:7e:bb:8a",
        True,
        'This can only be set when "nic_attach" is not a bridge device'
    ),
    # Invalid - trust_guest_rx_filters with E1000 model
    (
        NICDeviceType.DIRECT,
        "eth0",
        NICDeviceModel.E1000,
        "00:a0:99:7e:bb:8a",
        True,
        'This can only be set when "type" of NIC device is "VIRTIO"'
    ),
    # Invalid - MAC starting with ff
    (
        NICDeviceType.BRIDGE,
        "br0",
        NICDeviceModel.VIRTIO,
        "ff:a0:99:7e:bb:8a",
        False,
        'MAC address must not start with `ff`'
    ),
    # Valid - trust_guest_rx_filters with DIRECT + VIRTIO
    (
        NICDeviceType.DIRECT,
        "eth0",
        NICDeviceModel.VIRTIO,
        "00:a0:99:7e:bb:8a",
        True,
        None
    ),
])
def test_nic_device_validation(type_, source, model, mac, trust_guest, expected_error, mock_device_delegate):
    """Test comprehensive NIC device validation."""
    device = NICDevice(
        type_=type_,
        source=source,
        model=model,
        mac=mac,
        trust_guest_rx_filters=trust_guest,
        device_delegate=mock_device_delegate
    )

    errors = device.validate()

    if expected_error:
        assert len(errors) > 0
        assert any(expected_error in error[1] for error in errors), (
            f"Expected error '{expected_error}' not found in {errors}"
        )
    else:
        # Filter out any errors from the mock delegate
        validation_errors = [e for e in errors if 'trust_guest_rx_filters' in e[0] or 'mac' in e[0]]
        assert len(validation_errors) == 0, f"Unexpected validation errors: {validation_errors}"


def test_nic_pci_slot_without_pci_address(mock_device_delegate):
    """NIC devices without an explicit pci_address return None from pci_slot(),
    meaning they are excluded from cross-device PCI conflict checks."""
    device = NICDevice(
        type_=NICDeviceType.BRIDGE, source="br0",
        model=NICDeviceModel.VIRTIO, mac=None,
        trust_guest_rx_filters=False,
        device_delegate=mock_device_delegate,
    )
    assert device.pci_slot() is None


def test_nic_pci_slot_with_pci_address(mock_device_delegate):
    """NIC devices with a pci_address return (bus, slot), which is used by the
    cross-device conflict checker to detect collisions."""
    device = NICDevice(
        type_=NICDeviceType.BRIDGE, source="br0",
        model=NICDeviceModel.VIRTIO, mac=None,
        trust_guest_rx_filters=False,
        pci_address=PciAddress(bus=1, slot=3),
        device_delegate=mock_device_delegate,
    )
    assert device.pci_slot() == (1, 3)


@pytest.mark.parametrize("pci_address,expected_error_fields", [
    # valid: bus >= 1, domain 0, function 0
    (PciAddress(bus=1, slot=0), []),
    # domain != 0
    (PciAddress(bus=1, slot=0, domain=1), ['pci_address.domain']),
    # bus == 0 (root bus)
    (PciAddress(bus=0, slot=1), ['pci_address.bus']),
    # function != 0
    (PciAddress(bus=1, slot=0, function=1), ['pci_address.function']),
    # all three invalid at once
    (PciAddress(bus=0, slot=0, domain=1, function=2), [
        'pci_address.domain', 'pci_address.bus', 'pci_address.function',
    ]),
])
def test_nic_pci_address_validate_impl(pci_address, expected_error_fields, mock_device_delegate):
    """validate_impl() catches PciAddress fields that are invalid regardless of machine type:
    domain must be 0, bus must be >= 1 (root bus is too crowded), function must be 0."""
    device = NICDevice(
        type_=NICDeviceType.BRIDGE, source="br0",
        model=NICDeviceModel.VIRTIO, mac=None,
        trust_guest_rx_filters=False,
        pci_address=pci_address,
        device_delegate=mock_device_delegate,
    )
    errors = device.validate()
    error_fields = [e[0] for e in errors]
    for f in expected_error_fields:
        assert f in error_fields, f"Expected error on '{f}', got: {errors}"
    if not expected_error_fields:
        pci_errors = [e for e in errors if e[0].startswith('pci_address')]
        assert pci_errors == [], f"Unexpected pci_address errors: {pci_errors}"


@pytest.mark.parametrize("slot,machine_type,expect_error,error_fragment", [
    # PCIe (q35): slot 0 is the only valid slot on a pcie-root-port
    (0, "pc-q35-10.0",  False, None),
    (1, "pc-q35-10.0",  True,  "slot must be 0"),
    # PCIe (aarch64 virt): same rules as q35
    (0, "virt-9.2",     False, None),
    (1, "virt-9.2",     True,  "slot must be 0"),
    # i440fx: slot 0 is SHPC-reserved
    (0, "pc-i440fx-9.2", True,  "usable slots start at 1"),
    (1, "pc-i440fx-9.2", False, None),
    # unknown machine type treated conservatively as i440fx
    (0, None,            True,  "usable slots start at 1"),
    (1, None,            False, None),
])
def test_pci_slot_error_for_machine(slot, machine_type, expect_error, error_fragment):
    """pci_slot_error_for_machine() enforces PCIe point-to-point (slot == 0) and
    i440fx SHPC-reserved (slot != 0) rules; unknown machine type defaults to i440fx."""
    result = pci_slot_error_for_machine(slot, machine_type)
    if expect_error:
        assert result is not None
        assert error_fragment in result
    else:
        assert result is None
