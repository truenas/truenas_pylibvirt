from ..xml import xml_element
from .base import Device, DeviceXmlContext
from .utils import disk_from_number


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
