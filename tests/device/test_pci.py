"""Tests for PCI device validation and conflict detection."""
from __future__ import annotations

from unittest.mock import Mock
from xml.etree import ElementTree as ET

from truenas_pylibvirt.device import PCIDevice
from truenas_pylibvirt.domain.start_validator import StartValidationContext


def test_pci_device_exclusive():
    """Test that PCI devices are marked as exclusive."""
    assert PCIDevice.EXCLUSIVE_DEVICE is True


def test_pci_device_xml_generation(device_context, mock_device_delegate):
    """Test PCI device XML generation."""
    device = PCIDevice(
        domain="0000",
        bus="01",
        slot="00",
        function="0",
        pci_device="pci_0000_01_00_0",
        device_delegate=mock_device_delegate
    )

    xml_elements = device.xml(device_context)
    xml_str = ''.join(ET.tostring(elem, encoding='unicode') for elem in xml_elements).strip()

    expected = (
        '<hostdev mode="subsystem" type="pci" managed="yes">'
        '<source>'
        '<address domain="0x0000" bus="0x01" slot="0x00" function="0x0" />'
        '</source>'
        '</hostdev>'
    )

    assert xml_str == expected


def test_pci_identity(mock_device_delegate):
    """Test PCI device identity returns the PCI device name."""
    device = PCIDevice(
        domain="0000",
        bus="01",
        slot="00",
        function="0",
        pci_device="pci_0000_01_00_0",
        device_delegate=mock_device_delegate
    )

    assert device.identity() == "pci_0000_01_00_0"


def test_pci_conflict_detection_no_conflict(mock_device_delegate):
    """Test PCI device conflict detection when no other VM uses it."""
    device = PCIDevice(
        domain="0000",
        bus="01",
        slot="00",
        function="0",
        pci_device="pci_0000_01_00_0",
        device_delegate=mock_device_delegate
    )

    # Mock connection with no other VMs
    mock_conn = Mock()
    mock_conn.connection.listAllDomains.return_value = []

    context = StartValidationContext(
        connection=mock_conn,
        domain_uuid="test-vm-uuid"
    )

    errors = device.validate_start(context)
    assert len(errors) == 0


def test_pci_conflict_detection_with_conflict(mock_device_delegate):
    """Test PCI device conflict detection when another VM uses the same device."""
    device = PCIDevice(
        domain="0000",
        bus="01",
        slot="00",
        function="0",
        pci_device="pci_0000_01_00_0",
        device_delegate=mock_device_delegate
    )

    # Mock another VM using the same PCI device
    mock_domain = Mock()
    mock_domain.XMLDesc.return_value = '''
        <domain>
          <devices>
            <hostdev type="pci">
              <source>
                <address domain="0x0000" bus="0x01" slot="0x00" function="0x0"/>
              </source>
            </hostdev>
          </devices>
        </domain>
    '''
    mock_domain.isActive.return_value = True
    mock_domain.UUIDString.return_value = "other-vm-uuid"
    mock_domain.name.return_value = "other-vm"

    mock_conn = Mock()
    mock_conn.connection.listAllDomains.return_value = [mock_domain]

    context = StartValidationContext(
        connection=mock_conn,
        domain_uuid="test-vm-uuid"
    )

    errors = device.validate_start(context)
    assert len(errors) == 1
    assert "already in use by VM other-vm" in errors[0][1]
    assert "pci_0000_01_00_0" in errors[0][0]


def test_pci_no_conflict_with_self(mock_device_delegate):
    """Test that PCI device doesn't report conflict with itself."""
    device = PCIDevice(
        domain="0000",
        bus="01",
        slot="00",
        function="0",
        pci_device="pci_0000_01_00_0",
        device_delegate=mock_device_delegate
    )

    # Mock our own VM with the device
    mock_domain = Mock()
    mock_domain.XMLDesc.return_value = '''
        <domain>
          <devices>
            <hostdev type="pci">
              <source>
                <address domain="0x0000" bus="0x01" slot="0x00" function="0x0"/>
              </source>
            </hostdev>
          </devices>
        </domain>
    '''
    mock_domain.isActive.return_value = True
    mock_domain.UUIDString.return_value = "test-vm-uuid"  # Same as context
    mock_domain.name.return_value = "test-vm"

    mock_conn = Mock()
    mock_conn.connection.listAllDomains.return_value = [mock_domain]

    context = StartValidationContext(
        connection=mock_conn,
        domain_uuid="test-vm-uuid"  # Same UUID
    )

    errors = device.validate_start(context)
    assert len(errors) == 0  # No conflict with self


def test_pci_no_conflict_with_inactive_vm(mock_device_delegate):
    """Test that inactive VMs don't cause conflicts."""
    device = PCIDevice(
        domain="0000",
        bus="01",
        slot="00",
        function="0",
        pci_device="pci_0000_01_00_0",
        device_delegate=mock_device_delegate
    )

    # Mock an inactive VM with the same device
    mock_domain = Mock()
    mock_domain.XMLDesc.return_value = '''
        <domain>
          <devices>
            <hostdev type="pci">
              <source>
                <address domain="0x0000" bus="0x01" slot="0x00" function="0x0"/>
              </source>
            </hostdev>
          </devices>
        </domain>
    '''
    mock_domain.isActive.return_value = False  # VM is not running
    mock_domain.UUIDString.return_value = "other-vm-uuid"
    mock_domain.name.return_value = "other-vm"

    mock_conn = Mock()
    mock_conn.connection.listAllDomains.return_value = [mock_domain]

    context = StartValidationContext(
        connection=mock_conn,
        domain_uuid="test-vm-uuid"
    )

    errors = device.validate_start(context)
    assert len(errors) == 0  # Inactive VM doesn't cause conflict
