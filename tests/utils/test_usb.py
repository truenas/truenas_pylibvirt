"""Tests for building USB device names from the port a device is plugged into."""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from truenas_pylibvirt.utils.usb import (
    find_usb_device_by_ids,
    find_usb_device_by_libvirt_name,
    get_all_usb_devices,
    libvirt_device_name,
)


def _udev_device(sys_name, busnum, devnum, vendor_id='0627', product_id='0001', device_class='00'):
    device = Mock()
    device.sys_name = sys_name
    device.properties = {
        'BUSNUM': busnum,
        'DEVNUM': devnum,
        'ID_VENDOR_ID': vendor_id,
        'ID_MODEL_ID': product_id,
        'ID_VENDOR_FROM_DATABASE': 'Adomax Technology Co., Ltd',
        'ID_MODEL_FROM_DATABASE': 'QEMU Tablet',
    }
    device.attributes.get.return_value = device_class.encode()
    return device


@pytest.fixture
def udev_devices():
    """A device on a port whose number differs from its device number, plus one behind a hub."""
    devices = [
        _udev_device('usb1', '001', '001', vendor_id='1d6b', product_id='0002', device_class='09'),  # root hub
        _udev_device('1-1', '001', '002'),
        _udev_device('1-4.2', '001', '003', vendor_id='46f4', product_id='0002'),
    ]
    with patch('truenas_pylibvirt.utils.usb.Context') as context:
        context.return_value.list_devices.return_value = devices
        yield devices


@pytest.mark.parametrize('sys_name,expected', [
    ('1-1', 'usb_1_1'),
    ('1-4.2', 'usb_1_4_2'),
    ('2-10.3.1', 'usb_2_10_3_1'),
])
def test_libvirt_device_name_from_port(sys_name, expected):
    """A device name is the port path with its separators turned into underscores."""
    assert libvirt_device_name(sys_name) == expected


def test_get_all_usb_devices_keyed_by_port(udev_devices):
    """Devices are keyed by their port, not by the device number the kernel handed them."""
    devices = get_all_usb_devices()

    assert sorted(devices) == ['usb_1_1', 'usb_1_4_2']
    # Root hubs are not passthrough candidates
    assert 'usb_usb1' not in devices


def test_find_usb_device_by_libvirt_name_resolves_port(udev_devices):
    """The name names a port, so it resolves to whatever is plugged in there."""
    details = find_usb_device_by_libvirt_name('usb_1_1')

    assert details['error'] is None
    assert details['available'] is True
    # The device number is resolved fresh rather than read out of the name
    assert details['capability']['bus'] == '1'
    assert details['capability']['device'] == '2'


def test_find_usb_device_by_libvirt_name_behind_hub(udev_devices):
    """A device behind a hub carries the whole port path in its name."""
    details = find_usb_device_by_libvirt_name('usb_1_4_2')

    assert details['error'] is None
    assert details['capability']['product_id'] == '0x0002'


def test_find_usb_device_by_libvirt_name_not_found(udev_devices):
    """A name whose port holds nothing reports that rather than resolving to another device."""
    details = find_usb_device_by_libvirt_name('usb_1_2')

    assert details['error'] == 'USB device usb_1_2 not found'
    assert details['available'] is False


def test_find_usb_device_by_ids_returns_port_name(udev_devices):
    """Looking a device up by its ids yields the name of the port it occupies."""
    assert find_usb_device_by_ids('0x46f4', '0x0002') == 'usb_1_4_2'


def test_find_usb_device_by_libvirt_name_never_returns_a_hub(udev_devices):
    """A stored name that reaches a hub resolves to nothing rather than to the whole bus."""
    details = find_usb_device_by_libvirt_name('usb_usb1')

    assert details['error'] == 'USB device usb_usb1 not found'
    assert details['available'] is False


def test_find_usb_device_by_ids_never_returns_a_hub(udev_devices):
    """The ids of a hub name no passthrough candidate either."""
    assert find_usb_device_by_ids('0x1d6b', '0x0002') is None
