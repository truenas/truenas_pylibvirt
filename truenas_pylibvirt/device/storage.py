from dataclasses import dataclass
import enum

from ..xml import xml_element
from .base import Device, DeviceXmlContext
from .utils import disk_from_number


class StorageDeviceType(enum.Enum):
    AHCI = "AHCI"
    VIRTIO = "VIRTIO"


class StorageDeviceIoType(enum.Enum):
    NATIVE = "NATIVE"
    THREADS = "THREADS"
    IO_URING = "IO_URING"


@dataclass(kw_only=True)
class BaseStorageDevice(Device):
    type_: StorageDeviceType
    logical_sectorsize: int | None
    physical_sectorsize: int | None
    iotype: StorageDeviceIoType
    serial: str

    def xml(self, context: DeviceXmlContext):
        if self.type_ == StorageDeviceType.VIRTIO:
            target_bus = "virtio"
            target_dev = f"vd{disk_from_number(context.counters.next_virtual_device_no())}"
        else:
            target_bus = "sata"
            target_dev = f"sd{disk_from_number(context.counters.next_scsi_device_no())}"

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

        return [
            xml_element(
                "disk",
                attributes={"type": self._disk_type(), "device": "disk"},
                children=children,
            )
        ]

    def _disk_type(self) -> str:
        raise NotImplementedError

    def _source_xml(self, context: DeviceXmlContext):
        raise NotImplementedError()


@dataclass(kw_only=True)
class RawStorageDevice(BaseStorageDevice):
    path: str

    def _disk_type(self) -> str:
        return "file"

    def _source_xml(self, context: DeviceXmlContext):
        return xml_element("source", attributes={"file": self.path})


@dataclass(kw_only=True)
class DiskStorageDevice(BaseStorageDevice):
    path: str

    def _disk_type(self) -> str:
        return "block"

    def _source_xml(self, context: DeviceXmlContext):
        return xml_element("source", attributes={"dev": self.path})
