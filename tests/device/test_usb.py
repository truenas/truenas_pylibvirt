"""Tests for USB device validation and XML generation."""
from __future__ import annotations

from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET

from truenas_pylibvirt.device import USBDevice


def test_usb_device_exclusive():
    """Test that USB devices are marked as exclusive."""
    assert USBDevice.EXCLUSIVE_DEVICE is True


@patch('truenas_pylibvirt.device.usb.find_usb_device_by_libvirt_name')
def test_usb_device_xml_generation_by_name(mock_find_usb, device_context, mock_device_delegate):
    """Test USB device XML generation using device name."""
    # Mock USB device details
    mock_find_usb.return_value = {
        'capability': {
            'vendor_id': '0x1234',
            'product_id': '0x5678',
            'bus': '001',
            'device': '002',
        },
        'available': True,
    }

    device = USBDevice(
        vendor_id=None,
        product_id=None,
        device="usb_1_1",
        controller_type="usb3",
        device_delegate=mock_device_delegate
    )

    xml_elements = device.xml(device_context)
    xml_str = ''.join(ET.tostring(elem, encoding='unicode') for elem in xml_elements).strip()

    # Check key elements are present
    assert 'hostdev' in xml_str
    assert 'type="usb"' in xml_str
    assert 'vendor' in xml_str
    assert 'product' in xml_str


@patch('truenas_pylibvirt.device.usb.find_usb_device_by_ids')
@patch('truenas_pylibvirt.device.usb.find_usb_device_by_libvirt_name')
def test_usb_device_xml_generation_by_ids(mock_find_by_name, mock_find_by_ids, device_context, mock_device_delegate):
    """Test USB device XML generation using vendor/product IDs."""
    # Mock USB device discovery
    mock_find_by_ids.return_value = "usb_1_1"
    mock_find_by_name.return_value = {
        'capability': {
            'vendor_id': '0x1234',
            'product_id': '0x5678',
            'bus': '001',
            'device': '002',
        },
        'available': True,
    }

    device = USBDevice(
        vendor_id="0x1234",
        product_id="0x5678",
        device=None,
        controller_type="usb3",
        device_delegate=mock_device_delegate
    )

    xml_elements = device.xml(device_context)
    xml_str = ''.join(ET.tostring(elem, encoding='unicode') for elem in xml_elements).strip()

    assert 'hostdev' in xml_str
    assert 'type="usb"' in xml_str


def test_usb_identity_with_device_name(mock_device_delegate):
    """Test USB device identity when using device name."""
    device = USBDevice(
        vendor_id=None,
        product_id=None,
        device="usb_1_1",
        controller_type="usb3",
        device_delegate=mock_device_delegate
    )

    assert device.identity() == "usb_1_1"


def test_usb_identity_with_ids(mock_device_delegate):
    """Test USB device identity when using vendor/product IDs."""
    device = USBDevice(
        vendor_id="0x1234",
        product_id="0x5678",
        device=None,
        controller_type="usb3",
        device_delegate=mock_device_delegate
    )

    identity = device.identity()
    assert "0x5678" in identity
    assert "0x1234" in identity


@patch('truenas_pylibvirt.device.usb.find_usb_device_by_libvirt_name')
def test_usb_validation_device_and_ids_mutually_exclusive(mock_find_usb, mock_device_delegate):
    """Test that device and IDs cannot both be specified."""
    # Mock USB device discovery to avoid udev dependency
    mock_find_usb.return_value = {
        'capability': {
            'vendor_id': '0x1234',
            'product_id': '0x5678',
            'bus': '001',
            'device': '002',
        },
        'available': True,
    }

    device = USBDevice(
        vendor_id="0x1234",
        product_id="0x5678",
        device="usb_1_1",  # Both device and IDs specified
        controller_type="usb3",
        device_delegate=mock_device_delegate
    )

    errors = device.validate()
    assert len(errors) > 0
    assert any("device must be specified or USB details but not both" in error[1] for error in errors)


def test_usb_validation_missing_device_and_ids(mock_device_delegate):
    """Test that either device or IDs must be specified."""
    device = USBDevice(
        vendor_id=None,
        product_id=None,
        device=None,  # Nothing specified
        controller_type="usb3",
        device_delegate=mock_device_delegate
    )

    errors = device.validate()
    assert len(errors) > 0
    assert any("must be specified" in error[1] for error in errors)


def test_usb_conflict_detection(mock_device_delegate):
    """Test USB device conflict detection."""
    device = USBDevice(
        vendor_id="0x1234",
        product_id="0x5678",
        device=None,
        controller_type="usb3",
        device_delegate=mock_device_delegate
    )

    # Mock another VM using the same USB device
    mock_domain = Mock()
    mock_domain.XMLDesc.return_value = '''
        <domain>
          <devices>
            <hostdev type="usb">
              <source>
                <vendor id="0x1234" />
                <product id="0x5678" />
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

    from truenas_pylibvirt.domain.start_validator import StartValidationContext
    context = StartValidationContext(
        connection=mock_conn,
        domain_uuid="test-vm-uuid"
    )

    errors = device.validate_start(context)
    assert len(errors) == 1
    assert "already in use by VM other-vm" in errors[0][1]
