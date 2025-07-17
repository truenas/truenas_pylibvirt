import enum

from ..xml import xml_element
from .base import Device, DeviceXmlContext


class StorageDeviceType(enum.Enum):
    AHCI = "AHCI"
    VIRTIO = "VIRTIO"


class StorageDeviceIoType(enum.Enum):
    NATIVE = "NATIVE"
    THREADS = "THREADS"
    IO_URING = "IO_URING"


class BaseStorageDevice(Device):
    type_: StorageDeviceType
    logical_sectorsize: int | None
    physical_sectorsize: int | None
    iotype: StorageDeviceIoType
    serial: str

    def xml(self, context: DeviceXmlContext):
        if self.type_ == StorageDeviceType.VIRTIO:
            target_bus = "virtio"
            target_dev = f"vd{context.counters.next_virtual_device_no()}"
        else:
            target_bus = "ahci"
            target_dev = f"sd{context.counters.next_scsi_device_no()}"

        children = [
            xml_element("driver", attributes={
                "name": "qemu",
                "type": "raw",
                "cache": "none",
                "io": self.iotype.value.lower(),
                "discard": "unmap"
            }),
            self._source_xml(context),
            xml_element("target", attributes={"bus": target_bus, "dev": target_dev},),
            xml_element("serial", text=self.serial),
            xml_element("boot", attributes={"order": str(context.counters.next_boot_no())}),
        ]

        if self.logical_sectorsize:
            if self.physical_sectorsize:
                children.append(xml_element(
                    "blockio",
                    attributes={"physical_block_size": str(self.physical_sectorsize)}
                ))
            else:
                children.append(xml_element(
                    "blockio",
                    attributes={"logical_block_size": str(self.logical_sectorsize)}
                ))

    def _source_xml(self, context: DeviceXmlContext):
        raise NotImplementedError()


class RawStorageDevice(BaseStorageDevice):
    path: str

    def _source_xml(self, context: DeviceXmlContext):
        return xml_element("source", attributes={"file": self.path})


class DiskStorageDevice(BaseStorageDevice):
    path: str

    def _source_xml(self, context: DeviceXmlContext):
        return xml_element("source", attributes={"dev": self.path})
