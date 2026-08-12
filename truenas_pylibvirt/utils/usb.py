import re
from typing import Any

from pyudev import Context, Device as UdevDevice


# Regex to match libvirt USB device names (e.g., usb_1_2, usb_3_7)
RE_USB_DEVICE = re.compile(r'^usb_(\d+)_(\d+)$')


def get_usb_device_default_data() -> dict[str, Any]:
    """Default structure for USB device data."""
    return {
        'capability': {
            'vendor': None,
            'vendor_id': None,
            'product': None,
            'product_id': None,
            'bus': None,
            'device': None,
        },
        'available': False,
        'error': None,
        'description': '',
    }


def parse_libvirt_device_name(device_name: str) -> tuple[str, str] | None:
    """
    Parse libvirt USB device name (e.g., usb_1_2) to extract bus and device numbers.

    Returns:
        Tuple of (bus, device) or None if invalid format
    """
    match = RE_USB_DEVICE.match(device_name)
    if match:
        return match.group(1), match.group(2)
    return None


def is_usb_hub(udev_device: UdevDevice) -> bool:
    """
    Whether a udev device is a USB hub, root hubs included.

    A hub is never a passthrough candidate: a root hub is the bus itself, and handing a guest a
    hub hands it everything plugged into that hub.
    """
    try:
        device_class = udev_device.attributes.get('bDeviceClass')
    except (AttributeError, UnicodeDecodeError):
        return False

    return bool(device_class) and device_class.decode('utf-8', errors='ignore') == '09'


def libvirt_device_name(sys_name: str) -> str:
    """
    Build the libvirt device name of a USB device from its sysfs port path.

    The port path is the physical socket the device is plugged into (e.g. "1-2", or "1-4.2" for a
    device behind a hub) and stays the same across replugs and reboots, unlike the device number.

    Args:
        sys_name: Sysfs port path like "1-2" or "1-4.2"

    Returns:
        Libvirt device name (e.g., "usb_1_2" or "usb_1_4_2")
    """
    return f'usb_{sys_name.replace("-", "_").replace(".", "_")}'


def get_usb_device_details(udev_device: UdevDevice) -> dict[str, Any]:
    """Extract USB device details from udev device."""
    data = get_usb_device_default_data()

    # Get properties from udev
    props = udev_device.properties

    # Extract capability information - match libvirt format exactly
    # libvirt uses integers without leading zeros for bus and device
    bus_num = props.get('BUSNUM', '').lstrip('0') or '0' if props.get('BUSNUM') else None
    dev_num = props.get('DEVNUM', '').lstrip('0') or '0' if props.get('DEVNUM') else None
    data['capability']['bus'] = bus_num
    data['capability']['device'] = dev_num

    # Add 0x prefix to vendor/product IDs for libvirt compatibility
    vendor_id = props.get('ID_VENDOR_ID')
    product_id = props.get('ID_MODEL_ID')
    if vendor_id and not vendor_id.startswith('0x'):
        data['capability']['vendor_id'] = f"0x{vendor_id}"
    else:
        data['capability']['vendor_id'] = vendor_id if vendor_id else None

    if product_id and not product_id.startswith('0x'):
        data['capability']['product_id'] = f"0x{product_id}"
    else:
        data['capability']['product_id'] = product_id if product_id else None

    data['capability']['vendor'] = props.get('ID_VENDOR_FROM_DATABASE') or props.get('ID_VENDOR') or None
    data['capability']['product'] = props.get('ID_MODEL_FROM_DATABASE') or props.get('ID_MODEL') or None

    # Check if all required keys have values (matching middleware behavior)
    required_keys = ['bus', 'device', 'vendor_id', 'product_id']
    missing_keys = [k for k in required_keys if data['capability'][k] is None]

    if missing_keys:
        data['error'] = f'Missing required USB device information: {", ".join(missing_keys)}'
        data['available'] = False
    else:
        data['available'] = True

    # Build description
    vendor = data['capability']['vendor']
    product = data['capability']['product']
    if vendor and product:
        data['description'] = f"{product} by {vendor}"
    elif product:
        data['description'] = product
    elif vendor:
        data['description'] = f"Device by {vendor}"
    else:
        bus_str = data['capability']['bus'] or '?'
        dev_str = data['capability']['device'] or '?'
        data['description'] = f"USB Device {bus_str}:{dev_str}"

    return data


def find_usb_device_by_libvirt_name(device_name: str) -> dict[str, Any]:
    """
    Find USB device by libvirt device name (e.g., usb_1_2).

    Args:
        device_name: Libvirt device name like "usb_1_2"

    Returns:
        Device details dict or dict with error
    """
    context = Context()
    # Look for the USB device currently plugged into the port the name refers to
    for device in context.list_devices(subsystem='usb', DEVTYPE='usb_device'):
        if libvirt_device_name(device.sys_name) == device_name and not is_usb_hub(device):
            return get_usb_device_details(device)

    return {
        **get_usb_device_default_data(),
        'error': f'USB device {device_name} not found'
    }


def find_usb_device_by_ids(vendor_id: str, product_id: str) -> str | None:
    """
    Find USB device name by vendor and product IDs.

    Args:
        vendor_id: USB vendor ID (hex string like "0x0db0" or "0db0")
        product_id: USB product ID (hex string like "0x0076" or "0076")

    Returns:
        Libvirt device name (e.g., "usb_1_2") or None if not found
    """
    context = Context()

    # Normalize IDs (remove 0x prefix if present, convert to lowercase)
    # Keep the hex digits as-is (don't strip leading zeros from hex values)
    vendor_id = vendor_id.lower().replace('0x', '')
    product_id = product_id.lower().replace('0x', '')

    for device in context.list_devices(subsystem='usb', DEVTYPE='usb_device'):
        if is_usb_hub(device):
            continue

        props = device.properties

        # Get device IDs (they're already without 0x prefix in pyudev)
        device_vendor = props.get('ID_VENDOR_ID', '').lower()
        device_product = props.get('ID_MODEL_ID', '').lower()

        if device_vendor == vendor_id and device_product == product_id:
            # Build libvirt device name from the port the device is plugged into
            return libvirt_device_name(device.sys_name)

    return None


def get_all_usb_devices() -> dict[str, dict[str, Any]]:
    """
    Get all USB devices on the system.

    Returns:
        Dict mapping libvirt device names to device details
    """
    result = {}
    context = Context()

    for device in context.list_devices(subsystem='usb', DEVTYPE='usb_device'):
        if is_usb_hub(device):
            continue

        device_name = libvirt_device_name(device.sys_name)

        # Skip if already added (shouldn't happen but just in case)
        if device_name not in result:
            result[device_name] = get_usb_device_details(device)

    return result
