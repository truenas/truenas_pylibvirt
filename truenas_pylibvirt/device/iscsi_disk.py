from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from xml.etree import ElementTree

from .base import Device, DeviceXmlContext, QemuArgsContext


# RFC 3720 IQN: iqn.YYYY-MM.<reversed-domain>[:<suffix>]
IQN_RE = re.compile(r'^iqn\.\d{4}-\d{2}\.[a-zA-Z][a-zA-Z0-9\-\.]*(?::[^\s]*)?$')


@dataclass
class ISCSIDiskTarget:
    iqn: str
    luns: list[int] = field(default_factory=lambda: [0])


@dataclass(kw_only=True)
class ISCSIDiskDevice(Device):
    """iSCSI disks attached via QEMU's built-in initiator (block-iscsi.so).

    Libvirt has no native model for this; args are emitted via qemu_args()
    and injected into <qemu:commandline> at domain XML generation time.
    Each instance manages one virtio-scsi-pci controller and all disks
    behind it.  Use controller_slot to avoid PCI address conflicts with
    other devices on the root bus.
    """

    portal_address: str
    targets: list[ISCSIDiskTarget]
    initiator_iqn: str
    # PCI slot for the virtio-scsi-pci controller on the root bus (default avoids
    # common libvirt auto-assignments and the installer NIC at 0x1e).
    controller_slot: int = 0x15

    def xml(self, context: DeviceXmlContext) -> list[ElementTree.Element]:
        return []

    def qemu_args(self, context: QemuArgsContext) -> list[str]:
        mt = context.machine_type or ''
        # q35 and aarch64 virt are both PCIe-native (pcie-root); i440fx uses pci.0.
        root_bus = 'pcie.0' if ('q35' in mt or mt.startswith('virt')) else 'pci.0'
        # IPv6 addresses must be bracketed in iSCSI URIs.
        try:
            addr = ipaddress.ip_address(self.portal_address)
            portal = f"[{self.portal_address}]" if isinstance(addr, ipaddress.IPv6Address) else self.portal_address
        except ValueError:
            portal = self.portal_address
        controller_id = f"scsi-iscsi-{self.controller_slot:x}"
        args = [
            "-iscsi", f"initiator-name={self.initiator_iqn}",
            "-device",
            f"virtio-scsi-pci,id={controller_id},bus={root_bus},addr=0x{self.controller_slot:x}",
        ]
        drive_index = 0
        for target in self.targets:
            for lun in target.luns:
                drive_id = f"iscsi-{self.controller_slot:x}-{drive_index}"
                args += [
                    "-drive",
                    f"file=iscsi://{portal}/{target.iqn}/{lun}"
                    f",if=none,id={drive_id},format=raw,cache=none",
                    "-device", f"scsi-block,drive={drive_id},bus={controller_id}.0",
                ]
                drive_index += 1
        return args

    def pci_slot(self) -> tuple[int, int] | None:
        # Always placed on the root bus (bus index 0).
        return (0, self.controller_slot)

    def is_available_impl(self) -> bool:
        return True

    def identity_impl(self) -> str:
        first_iqn = self.targets[0].iqn if self.targets else ""
        return f"iscsi:{self.portal_address}:{first_iqn}"

    def validate_impl(self) -> list[tuple[str, str]]:
        verrors = []

        try:
            ipaddress.ip_address(self.portal_address)
        except ValueError:
            verrors.append(('portal_address', 'Must be a valid IPv4 or IPv6 address.'))

        if not self.targets:
            verrors.append(('targets', 'At least one target is required.'))
        else:
            for i, target in enumerate(self.targets):
                if not IQN_RE.match(target.iqn):
                    verrors.append((f'targets.{i}.iqn', f'Invalid IQN: {target.iqn!r}'))
                if not target.luns:
                    verrors.append((f'targets.{i}.luns', 'At least one LUN is required.'))
                else:
                    for j, lun in enumerate(target.luns):
                        if lun < 0:
                            verrors.append((f'targets.{i}.luns.{j}', 'LUN must be >= 0.'))

        if not self.initiator_iqn:
            verrors.append(('initiator_iqn', 'This field is required.'))
        elif not IQN_RE.match(self.initiator_iqn):
            verrors.append(('initiator_iqn', f'Invalid IQN: {self.initiator_iqn!r}'))

        if not (1 <= self.controller_slot <= 30):
            verrors.append(('controller_slot', 'Must be between 1 and 30 inclusive.'))

        return verrors
