import logging
from contextlib import contextmanager
from dataclasses import dataclass

import libvirt

from ..error import Error
from ..xml import xml_element
from .base import Device, DeviceXmlContext
from ..utils.pci import get_single_pci_device_details, iommu_enabled


logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class PCIDevice(Device):

    EXCLUSIVE_DEVICE = True  # PCI devices can only be used by one VM at a time

    domain: str
    bus: str
    slot: str
    function: str
    pci_device: str

    def xml(self, context: DeviceXmlContext):
        return [
            xml_element(
                "hostdev",
                attributes={
                    "mode": "subsystem",
                    "type": "pci",
                    "managed": "yes",
                },
                children=[
                    xml_element(
                        "source",
                        children=[
                            xml_element(
                                "address",
                                attributes={
                                    "domain": self.domain,
                                    "bus": self.bus,
                                    "slot": self.slot,
                                    "function": self.function,
                                },
                            ),
                        ],
                    ),
                ],
            )
        ]

    def is_available_impl(self) -> bool:
        pci_device = self.get_pci_device_details()
        return pci_device['available'] if pci_device else False

    def get_pci_device_details(self) -> dict | None:
        pci_device = get_single_pci_device_details(self.pci_device)
        return pci_device[self.pci_device] if pci_device else None

    def identity_impl(self) -> str:
        return self.pci_device

    def _is_device_in_domain_xml(self, domain_xml_root) -> bool:
        """Check if this PCI device is present in the domain XML"""
        for hostdev in domain_xml_root.findall(".//devices/hostdev[@type='pci']"):
            address = hostdev.find('.//source/address')
            if address is not None:
                if (address.get('domain') == self.domain and
                        address.get('bus') == self.bus and
                        address.get('slot') == self.slot and
                        address.get('function') == self.function):
                    return True
        return False

    @contextmanager
    def run(self, connection, domain_uuid: str):
        """
        Manage PCI device lifecycle:
        1. Detach from host driver on entry
        2. Reattach to host driver on exit (if not in use by other VMs)
        """
        # Detach from host driver
        try:
            node_device = connection.connection.nodeDeviceLookupByName(self.pci_device)
            node_device.dettach()
            logger.info(f'Detached PCI device {self.pci_device} from host')
        except libvirt.libvirtError as e:
            if 'already in use' in str(e).lower():
                logger.debug(f'PCI device {self.pci_device} already detached')
            else:
                raise Error(f'Failed to detach PCI device {self.pci_device}: {e}')

        try:
            yield
        finally:
            # Only reattach if not in use by other VMs
            in_use, vm_name = self._is_in_use_by_other_vms(connection, domain_uuid)
            if not in_use:
                try:
                    node_device = connection.connection.nodeDeviceLookupByName(self.pci_device)
                    node_device.reAttach()
                    logger.info(f'Reattached PCI device {self.pci_device} to host')
                except libvirt.libvirtError as e:
                    # Non-fatal - log but don't raise
                    logger.warning(f'Failed to reattach PCI device {self.pci_device}: {e}')
            else:
                logger.info(f'Not reattaching PCI device {self.pci_device} - still in use by VM {vm_name}')

    def validate_impl(self) -> list[tuple[str, str]]:
        verrors = []
        pci_device_details = self.get_pci_device_details()
        if not pci_device_details:
            verrors.append((
                'pptdev',
                f'Not a valid choice. The PCI device {self.pci_device} not found'
            ))
        elif pci_device_details['error']:
            verrors.append((
                'pptdev',
                f'Not a valid choice. The PCI device is not available: {pci_device_details['error']}'
            ))
        elif pci_device_details['critical']:
            verrors.append((
                'pptdev',
                f'{pci_device_details["controller_type"]!r} based PCI devices are critical for system function '
                'and cannot be used for PCI passthrough'
            ))

        if not iommu_enabled():
            verrors.append((
                'pptdev', 'IOMMU support is required.'
            ))

        return verrors
