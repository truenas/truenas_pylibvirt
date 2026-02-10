from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree

from .base import Device, DeviceXmlContext
from .gpu_utils import GPUBase


@dataclass(kw_only=True)
class GPUDevice(Device):

    gpu_type: str
    pci_address: str

    def __post_init__(self) -> None:
        super().__post_init__()
        self.gpu = GPUBase.from_data({
            'pci_address': self.pci_address,
            'gpu_type': self.gpu_type,
        })

    def is_available_impl(self) -> bool:
        return self.gpu.is_available()

    def identity_impl(self) -> str:
        return f'{self.gpu_type} {self.pci_address!r}'

    def validate_impl(self) -> list[tuple[str, str]]:
        return self.gpu.validate()

    def xml(self, context: DeviceXmlContext) -> list[ElementTree.Element]:
        return self.gpu.xml()
