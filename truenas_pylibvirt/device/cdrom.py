import os
from dataclasses import dataclass

from .base import Device, DeviceXmlContext
from .utils import disk_from_number
from ..xml import xml_element


@dataclass(kw_only=True)
class CDROMDevice(Device):

    path: str

    def xml(self, context: DeviceXmlContext):
        disk_number = context.counters.next_scsi_device_no()
        boot_number = context.counters.next_boot_no()

        return [
            xml_element(
                "disk",
                attributes={"type": "file", "device": "cdrom"},
                children=[
                    xml_element("driver", attributes={"name": "qemu", "type": "raw"}),
                    xml_element("source", attributes={"file": self.path}),
                    xml_element("target", attributes={"dev": f"sd{disk_from_number(disk_number)}", "bus": "sata"}),
                    xml_element("boot", attributes={"order": str(boot_number)}),
                ]
            )
        ]

    def identity_impl(self) -> str:
        return self.path

    def is_available_impl(self) -> bool:
        return os.path.exists(self.identity())

    def validate_impl(self) -> list[tuple[str, str]]:
        verrors = []
        if not self.path.strip():
            verrors.append(('path', 'Path is required for CDROM device'))
        elif not os.path.isabs(self.path):
            verrors.append(('path', 'Path must be an absolute path'))
        elif not os.path.exists(self.path):
            verrors.append(('path', f'Path {self.path} does not exist'))
        return verrors
