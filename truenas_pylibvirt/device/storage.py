from __future__ import annotations

from dataclasses import dataclass
import enum
import os
from xml.etree import ElementTree

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
    iotype: StorageDeviceIoType | None
    path: str
    serial: str | None

    def xml(self, context: DeviceXmlContext) -> list[ElementTree.Element]:
        if self.type_ == StorageDeviceType.VIRTIO:
            target_bus = "virtio"
            target_dev = f"vd{disk_from_number(context.counters.next_virtual_device_no())}"
        else:
            target_bus = "sata"
            target_dev = f"sd{disk_from_number(context.counters.next_scsi_device_no())}"

        children = [
            xml_element("driver", attributes={
                "type": "raw",
                "cache": "none",
                "discard": "unmap"
            } | ({"io": self.iotype.value.lower()} if self.iotype else {})),
            self._source_xml(context),
            xml_element("target", attributes={"bus": target_bus, "dev": target_dev},),
            xml_element("boot", attributes={"order": str(context.counters.next_boot_no())}),
        ]
        if self.serial:
            children.append(xml_element("serial", text=self.serial))

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

    def _source_xml(self, context: DeviceXmlContext) -> ElementTree.Element:
        raise NotImplementedError()

    def validate_impl(self) -> list[tuple[str, str]]:
        verrors = []
        if self.physical_sectorsize and not self.logical_sectorsize:
            verrors.append(
                (
                    'logical_sectorsize',
                    'This field "logical_sectorsize" must be provided when physical_sectorsize is specified.'
                )
            )
        if not self.path:
            verrors.append(('path', 'This field is required.'))
        return verrors

    def identity_impl(self) -> str:
        return self.path

    def is_available_impl(self) -> bool:
        return os.path.exists(self.identity())


@dataclass(kw_only=True)
class RawStorageDevice(BaseStorageDevice):

    def _disk_type(self) -> str:
        return "file"

    def _source_xml(self, context: DeviceXmlContext) -> ElementTree.Element:
        return xml_element("source", attributes={"file": self.path})


@dataclass(kw_only=True)
class DiskStorageDevice(BaseStorageDevice):

    def _disk_type(self) -> str:
        return "block"

    def _source_xml(self, context: DeviceXmlContext) -> ElementTree.Element:
        return xml_element("source", attributes={"dev": self.path})

    def validate_impl(self) -> list[tuple[str, str]]:
        verrors = super().validate_impl()
        if self.path and not self.path.startswith("/dev/zvol"):
            verrors.append(("path", "Disk path must start with '/dev/zvol/'."))
        return verrors
