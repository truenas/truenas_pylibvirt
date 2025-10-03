import functools
import os
import re

from pyudev import Context, Device as UdevDevice

from .iommu import get_iommu_groups_info, get_pci_device_class, SENSITIVE_PCI_DEVICE_TYPES

RE_DEVICE_PATH = re.compile(r'pci_(\w+)_(\w+)_(\w+)_(\w+)')


@functools.cache
def iommu_enabled() -> bool:
    """Returns "true" if iommu is enabled, "false" otherwise"""
    return os.path.exists('/sys/kernel/iommu_groups')


def get_pci_device_default_data() -> dict:
    return {
        'capability': {
            'class': None,
            'domain': None,
            'bus': None,
            'slot': None,
            'function': None,
            'product': 'Not Available',
            'vendor': 'Not Available',
        },
        'controller_type': None,
        'critical': False,
        'iommu_group': None,
        'available': False,
        'drivers': [],
        'error': None,
        'device_path': None,
        'reset_mechanism_defined': False,
        'description': '',
    }


def get_pci_device_details(obj: UdevDevice, iommu_info: dict) -> dict:
    data = get_pci_device_default_data()
    if not (igi := iommu_info.get(obj.sys_name)):
        data['error'] = 'Unable to determine iommu group'

    dbs, func = obj.sys_name.split('.')
    dom, bus, slot = dbs.split(':')
    device_path = os.path.join('/sys/bus/pci/devices', obj.sys_name)
    cap_class = f'{(obj.attributes.get("class") or b"").decode()}' or get_pci_device_class(device_path)
    controller_type = obj.properties.get('ID_PCI_SUBCLASS_FROM_DATABASE') or SENSITIVE_PCI_DEVICE_TYPES.get(
        cap_class[:6]
    )

    drivers = []
    if driver := obj.properties.get('DRIVER'):
        drivers.append(driver)

    data['capability']['class'] = cap_class or None
    data['capability']['domain'] = f'{int(dom, base=16)}'
    data['capability']['bus'] = f'{int(bus, base=16)}'
    data['capability']['slot'] = f'{int(slot, base=16)}'
    data['capability']['function'] = f'{int(func, base=16)}'
    data['capability']['product'] = obj.properties.get('ID_MODEL_FROM_DATABASE', 'Not Available')
    data['capability']['vendor'] = obj.properties.get('ID_VENDOR_FROM_DATABASE', 'Not Available')
    data['controller_type'] = controller_type
    # Use critical information from iommu_info if available
    # If we cannot find the iommu entry, we mark the device as critical by default
    data['critical'] = True
    # Only include number and addresses in iommu_group for API compatibility
    data['iommu_group'] = None
    data['drivers'] = drivers
    data['device_path'] = os.path.join('/sys/bus/pci/devices', obj.sys_name)
    data['reset_mechanism_defined'] = os.path.exists(os.path.join(data['device_path'], 'reset'))

    if igi:
        data.update({
            'critical': igi['critical'],
            'iommu_group': {
                'number': igi['number'],
                'addresses': igi['addresses'],
            },
        })

    data['available'] = all(i == 'vfio-pci' for i in drivers) and not data['critical']

    prefix = obj.sys_name + (f' {controller_type!r}' if controller_type else '')
    vendor = data['capability']['vendor'].strip()
    suffix = data['capability']['product'].strip()
    if vendor and suffix:
        data['description'] = f'{prefix}: {suffix} by {vendor!r}'
    else:
        data['description'] = prefix

    return data


def get_all_pci_devices_details() -> dict:
    result = dict()
    iommu_info = get_iommu_groups_info(get_critical_info=True)
    for i in Context().list_devices(subsystem='pci'):
        key = f"pci_{i.sys_name.replace(':', '_').replace('.', '_')}"
        result[key] = get_pci_device_details(i, iommu_info)

    return result


def get_single_pci_device_details(device: str) -> dict:
    result = dict()
    iommu_info = get_iommu_groups_info(get_critical_info=True)
    for i in filter(
        lambda x: x.sys_name == RE_DEVICE_PATH.sub(r'\1:\2:\3.\4', device),
        Context().list_devices(subsystem='pci')
    ):
        key = f"pci_{i.sys_name.replace(':', '_').replace('.', '_')}"
        result[key] = get_pci_device_details(i, iommu_info)
    return result
