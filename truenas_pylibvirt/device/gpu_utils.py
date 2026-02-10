from __future__ import annotations

import contextlib
import functools
import os
import pathlib
from abc import ABC, abstractmethod
from typing import Any
from xml.etree import ElementTree

from ..utils.gpu import get_gpus, parse_nvidia_info_file
from ..utils.pci import get_single_pci_device_details, normalize_pci_address
from ..xml import xml_element


class GPUBase(ABC):

    _registry: dict[str, type[GPUBase]] = {}

    def __init__(self, pci_address: str, gpu_type: str, **kwargs: Any) -> None:
        self.pci_address = pci_address
        self.gpu_type = gpu_type

    def __init_subclass__(cls, gpu_type: str | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if gpu_type is not None:
            cls._registry[gpu_type.lower()] = cls

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> GPUBase:
        return cls._registry[data['gpu_type'].lower()](**data)

    def is_available(self) -> bool:
        pci_device = self.pci_device_details()
        return all(d != 'vfio-pci' for d in pci_device['drivers']) if pci_device else False

    def pci_device_details(self) -> dict[str, Any] | None:
        pci_addr = normalize_pci_address(self.pci_address)
        return get_single_pci_device_details(pci_addr).get(pci_addr)

    def validate(self) -> list[tuple[str, str]]:
        verrors = []
        pci_device_details = self.pci_device_details()
        if not pci_device_details:
            verrors.append((
                'pci_address',
                f'Not a valid choice. The GPU device {self.pci_address} not found'
            ))
        elif pci_device_details['error']:
            verrors.append((
                'pci_address',
                f'Not a valid choice. The GPU device is not available: {pci_device_details["error"]}'
            ))

        if not any(
            gpu for gpu in filter(
                lambda g: g['vendor'] == self.gpu_type and g['addr']['pci_slot'] == self.pci_address,
                get_gpus()
            )
        ):
            verrors.append((
                'gpu_type',
                f'Unable to locate {self.gpu_type!r} GPU device at {self.pci_address!r} PCI address'
            ))

        return verrors

    @abstractmethod
    def driver_xml(self) -> list[ElementTree.Element]:
        ...

    @abstractmethod
    def xml(self) -> list[ElementTree.Element]:
        ...


class DRMBase(GPUBase):

    @property
    def render_device_dir_path(self) -> str:
        return os.path.join('/sys/bus/pci/devices', self.pci_address, 'drm')

    @functools.cached_property
    def render_device_path(self) -> str | None:
        try:
            render_node = next((
                p.name for p in pathlib.Path(self.render_device_dir_path).iterdir() if p.name.startswith('render')
            ), None)
            render_node_path = f'/dev/dri/{render_node}' if render_node else None
            return render_node_path if render_node_path and os.path.exists(render_node_path) else None
        except FileNotFoundError:
            return None

    def is_available(self) -> bool:
        return super().is_available() and self.render_device_path is not None

    def validate(self) -> list[tuple[str, str]]:
        # We would like to ensure that we have compute/render node available
        verrors = super().validate()
        if verrors:
            # No point in continuing if PCI device cannot be located
            return verrors

        if not self.render_device_path:
            verrors.append(('pci_address', 'Unable to locate compute/render node for GPU'))
        return verrors

    def xml(self) -> list[ElementTree.Element]:
        return [
            xml_element(
                'hostdev', attributes={'mode': 'capabilities', 'type': 'misc'}, children=[
                    xml_element('source', children=[
                        xml_element('char', text=self.render_device_path),
                    ]),
                ]
            ),
        ]


class AMD(DRMBase, gpu_type='AMD'):

    DRIVER_PATH = '/dev/kfd'

    def is_available(self) -> bool:
        return super().is_available() and os.path.exists(self.DRIVER_PATH)

    def validate(self) -> list[tuple[str, str]]:
        # We should ensure that we have /dev/kfd available
        verrors = super().validate()
        if verrors:
            # No point in continuing if PCI device or compute node cannot be located
            return verrors

        if not os.path.exists(self.DRIVER_PATH):
            verrors.append(('gpu_type', f'{self.DRIVER_PATH!r} must exist for AMD GPUs'))
        return verrors

    def driver_xml(self) -> list[ElementTree.Element]:
        return [
            xml_element(
                'hostdev', attributes={'mode': 'capabilities', 'type': 'misc'}, children=[
                    xml_element('source', children=[
                        xml_element('char', text=self.DRIVER_PATH),
                    ]),
                ]
            ),
        ]


class INTEL(DRMBase, gpu_type='INTEL'):
    pass


class NVIDIA(GPUBase, gpu_type='NVIDIA'):

    DRIVERS_PATH = ['/dev/nvidia-uvm', '/dev/nvidiactl']

    @property
    def drivers_available(self) -> bool:
        return all(os.path.exists(path) for path in self.DRIVERS_PATH)

    @property
    def device_info_path(self) -> str:
        return os.path.join('/proc/driver/nvidia/gpus', self.pci_address, 'information')

    @functools.cached_property
    def device_path(self) -> str | None:
        with contextlib.suppress(FileNotFoundError):
            with open(self.device_info_path, 'r') as f:
                info, _ = parse_nvidia_info_file(f)
                if (path := f'/dev/nvidia{info.get("device_minor")}') and os.path.exists(path):
                    return path

        return None

    def is_available(self) -> bool:
        return super().is_available() and self.drivers_available and self.device_path is not None

    def validate(self) -> list[tuple[str, str]]:
        # We will like to validate following things here:
        # nvidia drivers are available i.e nvidia-uvm / nvidiactl
        # nvidia gpu's device node is available
        verrors = super().validate()
        if self.drivers_available is False:
            verrors.append(('gpu_type', f'NVIDIA drivers ({", ".join(self.DRIVERS_PATH)}) must exist for NVIDIA GPUs'))

        if not self.device_path:
            verrors.append(('pci_address', 'Unable to locate NVIDIA device node'))

        return verrors

    def driver_xml(self) -> list[ElementTree.Element]:
        return [
            xml_element(
                'hostdev', attributes={'mode': 'capabilities', 'type': 'misc'}, children=[
                    xml_element('source', children=[
                        xml_element('char', text=driver_path),
                    ]),
                ]
            ) for driver_path in self.DRIVERS_PATH
        ]

    def xml(self) -> list[ElementTree.Element]:
        return [
            xml_element(
                'hostdev', attributes={'mode': 'capabilities', 'type': 'misc'}, children=[
                    xml_element('source', children=[
                        xml_element('char', text=self.device_path),
                    ]),
                ]
            ),
        ]
