"""Tests for USB device validation and XML generation."""
from __future__ import annotations

from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET

import pytest

from truenas_pylibvirt import DeviceNotFoundError
from truenas_pylibvirt.device import USBDevice
from truenas_pylibvirt.utils.usb import get_usb_device_default_data


def _capability(vendor_id, product_id, bus='1', device='2'):
    """What `find_usb_device_by_libvirt_name` returns for a device that is present.

    Bus and device numbers are unpadded because that is what the lookup produces; a padded
    fixture would assert against a shape production cannot emit.
    """
    details = get_usb_device_default_data()
    details['capability'].update({
        'vendor': 'Test vendor',
        'vendor_id': vendor_id,
        'product': 'Test product',
        'product_id': product_id,
        'bus': bus,
        'device': device,
    })
    details['available'] = True
    details['description'] = 'Test product by Test vendor'
    return details


def _not_found(device_name):
    """What it returns for a name whose port holds nothing. Notably, never `None`."""
    return {**get_usb_device_default_data(), 'error': f'USB device {device_name} not found'}


def test_usb_device_exclusive():
    """Test that USB devices are marked as exclusive."""
    assert USBDevice.EXCLUSIVE_DEVICE is True


@patch('truenas_pylibvirt.device.usb.find_usb_device_by_libvirt_name')
def test_usb_device_xml_generation_by_name(mock_find_usb, device_context, mock_device_delegate):
    """Test USB device XML generation using device name."""
    mock_find_usb.return_value = _capability('0x1234', '0x5678')

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
    mock_find_by_ids.return_value = "usb_1_1"
    mock_find_by_name.return_value = _capability('0x1234', '0x5678')

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
    mock_find_usb.return_value = _capability('0x1234', '0x5678')

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


def _hostdev_bus(hostdev):
    address = hostdev.find("address[@type='usb']")
    return address.get('bus') if address is not None else None


@patch('truenas_pylibvirt.device.usb.find_usb_device_by_ids')
@patch('truenas_pylibvirt.device.usb.find_usb_device_by_libvirt_name')
def test_usb_two_devices_same_type_single_controller(
    mock_find_by_name, mock_find_by_ids, device_context, mock_device_delegate
):
    """Two distinct devices sharing a controller type emit exactly one controller, shared by both."""
    mock_find_by_ids.side_effect = lambda v, p: {
        ('0x80ee', '0x0021'): 'usb_1_2',
        ('0x0718', '0x7722'): 'usb_3_4',
    }.get((v, p))
    mock_find_by_name.side_effect = lambda n: {
        'usb_1_2': _capability('0x80ee', '0x0021'),
        'usb_3_4': _capability('0x0718', '0x7722'),
    }.get(n) or _not_found(n)

    first = USBDevice(
        vendor_id='0x80ee', product_id='0x0021', device=None,
        controller_type='qemu-xhci', device_delegate=mock_device_delegate,
    )
    second = USBDevice(
        vendor_id='0x0718', product_id='0x7722', device=None,
        controller_type='qemu-xhci', device_delegate=mock_device_delegate,
    )

    first_elements = first.xml(device_context)
    second_elements = second.xml(device_context)

    controllers = [e for e in first_elements + second_elements if e.tag == 'controller']
    hostdevs = [e for e in first_elements + second_elements if e.tag == 'hostdev']
    assert len(controllers) == 1
    assert len(hostdevs) == 2
    # The second device of the same type must not re-emit the controller.
    assert [e for e in second_elements if e.tag == 'controller'] == []

    index = controllers[0].get('index')
    assert all(_hostdev_bus(hostdev) == index for hostdev in hostdevs)


@patch('truenas_pylibvirt.device.usb.find_usb_device_by_ids')
@patch('truenas_pylibvirt.device.usb.find_usb_device_by_libvirt_name')
def test_usb_two_devices_different_types_two_controllers(
    mock_find_by_name, mock_find_by_ids, device_context, mock_device_delegate
):
    """Two devices with different non-default controller types each get their own controller."""
    mock_find_by_ids.side_effect = lambda v, p: {
        ('0x80ee', '0x0021'): 'usb_1_2',
        ('0x0718', '0x7722'): 'usb_3_4',
    }.get((v, p))
    mock_find_by_name.side_effect = lambda n: {
        'usb_1_2': _capability('0x80ee', '0x0021'),
        'usb_3_4': _capability('0x0718', '0x7722'),
    }.get(n) or _not_found(n)

    first = USBDevice(
        vendor_id='0x80ee', product_id='0x0021', device=None,
        controller_type='qemu-xhci', device_delegate=mock_device_delegate,
    )
    second = USBDevice(
        vendor_id='0x0718', product_id='0x7722', device=None,
        controller_type='ehci', device_delegate=mock_device_delegate,
    )

    first_elements = first.xml(device_context)
    second_elements = second.xml(device_context)

    controllers = [e for e in first_elements + second_elements if e.tag == 'controller']
    assert len(controllers) == 2
    assert len({c.get('index') for c in controllers}) == 2

    first_controller = next(e for e in first_elements if e.tag == 'controller')
    second_controller = next(e for e in second_elements if e.tag == 'controller')
    first_hostdev = next(e for e in first_elements if e.tag == 'hostdev')
    second_hostdev = next(e for e in second_elements if e.tag == 'hostdev')
    assert _hostdev_bus(first_hostdev) == first_controller.get('index')
    assert _hostdev_bus(second_hostdev) == second_controller.get('index')


@patch('truenas_pylibvirt.device.usb.find_usb_device_by_libvirt_name')
def test_usb_nec_xhci_no_controller_bus_zero(mock_find_usb, device_context, mock_device_delegate):
    """nec-xhci is libvirt's implicit controller (index 0) and never emits an explicit element."""
    mock_find_usb.side_effect = lambda n: {
        'usb_1_2': _capability('0x80ee', '0x0021'),
        'usb_3_4': _capability('0x0718', '0x7722'),
    }.get(n) or _not_found(n)

    first = USBDevice(
        vendor_id=None, product_id=None, device='usb_1_2',
        controller_type='nec-xhci', device_delegate=mock_device_delegate,
    )
    second = USBDevice(
        vendor_id=None, product_id=None, device='usb_3_4',
        controller_type='nec-xhci', device_delegate=mock_device_delegate,
    )

    elements = first.xml(device_context) + second.xml(device_context)
    assert [e for e in elements if e.tag == 'controller'] == []
    hostdevs = [e for e in elements if e.tag == 'hostdev']
    assert len(hostdevs) == 2
    assert all(_hostdev_bus(hostdev) == '0' for hostdev in hostdevs)


@patch('truenas_pylibvirt.device.usb.find_usb_device_by_libvirt_name')
def test_usb_controller_type_none_no_controller_no_address(
    mock_find_usb, device_context, mock_device_delegate
):
    """A device without a controller type (e.g. containers) emits no controller and no address."""
    mock_find_usb.return_value = _capability('0x80ee', '0x0021')

    device = USBDevice(
        vendor_id=None, product_id=None, device='usb_1_2',
        controller_type=None, device_delegate=mock_device_delegate,
    )

    elements = device.xml(device_context)
    assert [e for e in elements if e.tag == 'controller'] == []
    hostdev = next(e for e in elements if e.tag == 'hostdev')
    assert hostdev.find("address[@type='usb']") is None


@patch('truenas_pylibvirt.device.usb.find_usb_device_by_libvirt_name')
def test_usb_mixed_nec_and_qemu_xhci_indices(mock_find_usb, device_context, mock_device_delegate):
    """nec-xhci and qemu-xhci devices coexist without duplicate or colliding indices."""
    mock_find_usb.side_effect = lambda n: {
        'usb_1_2': _capability('0x80ee', '0x0021'),
        'usb_3_4': _capability('0x0718', '0x7722'),
    }.get(n) or _not_found(n)

    nec = USBDevice(
        vendor_id=None, product_id=None, device='usb_1_2',
        controller_type='nec-xhci', device_delegate=mock_device_delegate,
    )
    qemu = USBDevice(
        vendor_id=None, product_id=None, device='usb_3_4',
        controller_type='qemu-xhci', device_delegate=mock_device_delegate,
    )

    nec_elements = nec.xml(device_context)
    qemu_elements = qemu.xml(device_context)

    assert [e for e in nec_elements if e.tag == 'controller'] == []
    nec_hostdev = next(e for e in nec_elements if e.tag == 'hostdev')
    assert _hostdev_bus(nec_hostdev) == '0'

    qemu_controllers = [e for e in qemu_elements if e.tag == 'controller']
    assert len(qemu_controllers) == 1
    qemu_hostdev = next(e for e in qemu_elements if e.tag == 'hostdev')
    assert _hostdev_bus(qemu_hostdev) == qemu_controllers[0].get('index')
    assert qemu_controllers[0].get('index') != '0'


@patch('truenas_pylibvirt.device.usb.find_usb_device_by_libvirt_name')
def test_usb_port_attribute_omitted(mock_find_usb, device_context, mock_device_delegate):
    """The device address omits the port so libvirt auto-assigns a free port on the shared bus."""
    mock_find_usb.return_value = _capability('0x80ee', '0x0021')

    device = USBDevice(
        vendor_id=None, product_id=None, device='usb_1_2',
        controller_type='qemu-xhci', device_delegate=mock_device_delegate,
    )

    hostdev = next(e for e in device.xml(device_context) if e.tag == 'hostdev')
    address = hostdev.find("address[@type='usb']")
    assert address is not None
    assert address.get('port') is None


@patch('truenas_pylibvirt.device.usb.find_usb_device_by_libvirt_name')
def test_usb_missing_device_raises_and_does_not_consume_controller_index(
    mock_find_usb, device_context, mock_device_delegate
):
    """An empty port aborts the start rather than silently dropping the device, and it does so
    before touching the counters, so a later device of the same type still gets the first
    controller index."""
    mock_find_usb.side_effect = lambda n: {
        'usb_3_4': _capability('0x0718', '0x7722'),
    }.get(n) or _not_found(n)

    phantom = USBDevice(
        vendor_id=None, product_id=None, device='usb_missing',
        controller_type='qemu-xhci', device_delegate=mock_device_delegate,
    )
    real = USBDevice(
        vendor_id=None, product_id=None, device='usb_3_4',
        controller_type='qemu-xhci', device_delegate=mock_device_delegate,
    )

    with pytest.raises(DeviceNotFoundError, match='usb_missing'):
        phantom.xml(device_context)

    real_elements = real.xml(device_context)
    controllers = [e for e in real_elements if e.tag == 'controller']
    assert len(controllers) == 1
    real_hostdev = next(e for e in real_elements if e.tag == 'hostdev')
    assert _hostdev_bus(real_hostdev) == controllers[0].get('index')


@patch('truenas_pylibvirt.device.usb.find_usb_device_by_libvirt_name')
def test_usb_interleaved_types_reuse_existing_controller(
    mock_find_usb, device_context, mock_device_delegate
):
    """A type seen again after an intervening different type reuses its controller index and
    emits no second controller."""
    mock_find_usb.side_effect = lambda n: {
        'usb_1_2': _capability('0x80ee', '0x0021'),
        'usb_3_4': _capability('0x0718', '0x7722'),
        'usb_5_6': _capability('0x1d6b', '0x0003'),
    }.get(n) or _not_found(n)

    first_ehci = USBDevice(
        vendor_id=None, product_id=None, device='usb_1_2',
        controller_type='ehci', device_delegate=mock_device_delegate,
    )
    qemu = USBDevice(
        vendor_id=None, product_id=None, device='usb_3_4',
        controller_type='qemu-xhci', device_delegate=mock_device_delegate,
    )
    second_ehci = USBDevice(
        vendor_id=None, product_id=None, device='usb_5_6',
        controller_type='ehci', device_delegate=mock_device_delegate,
    )

    first_elements = first_ehci.xml(device_context)
    qemu_elements = qemu.xml(device_context)
    second_elements = second_ehci.xml(device_context)

    first_controller = next(e for e in first_elements if e.tag == 'controller')
    qemu_controller = next(e for e in qemu_elements if e.tag == 'controller')
    assert first_controller.get('index') != qemu_controller.get('index')

    # The second ehci shares the first ehci's controller, so it emits no controller of its own.
    assert [e for e in second_elements if e.tag == 'controller'] == []
    second_hostdev = next(e for e in second_elements if e.tag == 'hostdev')
    assert _hostdev_bus(second_hostdev) == first_controller.get('index')


@patch('truenas_pylibvirt.device.usb.find_usb_device_by_ids')
def test_usb_missing_ids_raise(mock_find_by_ids, device_context, mock_device_delegate):
    """A device identified by ids that are not connected fails the start instead of being dropped.

    Dropping it silently produced a VM that booted without hardware it was configured with, which
    nothing we expose records: the row is still listed, and the domain XML never mentions it.
    """
    mock_find_by_ids.return_value = None

    device = USBDevice(
        vendor_id='0x0718', product_id='0x7722', device=None,
        controller_type='qemu-xhci', device_delegate=mock_device_delegate,
    )

    with pytest.raises(DeviceNotFoundError, match='0x7722'):
        device.xml(device_context)


@patch('truenas_pylibvirt.device.usb.find_usb_device_by_libvirt_name')
def test_usb_xml_serialises(mock_find_usb, device_context, mock_device_delegate):
    """The generated elements survive serialisation.

    A lookup that failed used to yield a capability full of `None`s, which builds an element tree
    happily and only blows up here, far from anything naming USB.
    """
    mock_find_usb.return_value = _capability('0x80ee', '0x0021')

    device = USBDevice(
        vendor_id=None, product_id=None, device='usb_1_2',
        controller_type='qemu-xhci', device_delegate=mock_device_delegate,
    )

    hostdev = next(e for e in device.xml(device_context) if e.tag == 'hostdev')
    serialised = ET.tostring(hostdev, encoding='unicode')

    assert 'id="0x80ee"' in serialised
    assert 'id="0x0021"' in serialised
    assert 'bus="1" device="2"' in serialised


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
