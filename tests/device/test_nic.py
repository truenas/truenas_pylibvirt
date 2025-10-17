"""Tests for NIC device XML generation and validation."""
from __future__ import annotations

import pytest
from xml.etree import ElementTree as ET

from truenas_pylibvirt.device import NICDevice, NICDeviceType, NICDeviceModel


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
