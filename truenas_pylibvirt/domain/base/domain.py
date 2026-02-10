from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, Callable, Generator

from .configuration import BaseDomainConfiguration
from ...device.manager import DeviceManager

if TYPE_CHECKING:
    from ..container.domain import ContainerDomainContext
    from .xml import BaseDomainXmlGenerator


class BaseDomain:
    xml_generator_class: Callable[[BaseDomain, ContainerDomainContext], BaseDomainXmlGenerator] = NotImplemented

    def __init__(self, configuration: BaseDomainConfiguration):
        self.configuration = configuration
        self.device_manager = DeviceManager(configuration.devices, domain_uuid=configuration.uuid)

    def xml_generator(self, context: ContainerDomainContext) -> BaseDomainXmlGenerator:
        return self.xml_generator_class(self, context)

    @contextlib.contextmanager
    def run(self) -> Generator[Any, None, None]:
        yield

    def pid(self) -> int | None:
        raise NotImplementedError

    def undefine(self, libvirt_domain: Any) -> None:
        raise NotImplementedError
