from __future__ import annotations

from typing import TYPE_CHECKING
from xml.etree import ElementTree

from ...device.base import DeviceXmlContext
from ...device.counters import Counters
from ...device.pci import PCIDevice
from ...xml import xml_element
from .configuration import Time

if TYPE_CHECKING:
    from .domain import BaseDomain
    from ..container.domain import ContainerDomainContext


class BaseDomainXmlGenerator:
    def __init__(self, domain: BaseDomain, context: ContainerDomainContext) -> None:
        self.domain = domain
        self.context = context

    def generate(self) -> ElementTree.Element:
        return xml_element(
            "domain",
            attributes={
                "id": self.domain.configuration.uuid,
                "type": self._type(),
            },
            children=self._children(),
        )

    def _element(
            self,
            tag: str,
            *,
            attributes: dict[str, str] | None = None,
            children: list[ElementTree.Element] | None = None,
            text: str | None = None,
    ) -> ElementTree.Element:
        element = ElementTree.Element(tag, **(attributes or {}))  # type: ignore[arg-type]

        for child in children or []:
            element.append(child)

        if text is not None:
            element.text = text

        return element

    def _type(self) -> str:
        raise NotImplementedError()

    def _children(self) -> list[ElementTree.Element]:
        children = [
            xml_element("name", text=self.domain.configuration.uuid),
            xml_element("uuid", text=self.domain.configuration.uuid),
            xml_element("title", text=self.domain.configuration.name),
            xml_element("description", text=self.domain.configuration.description),
            self._os_xml(),
            *self._cpu_xml(),
            *self._memory_xml(),
            self._clock_xml(),
            self._devices_xml(),
            self._features_xml(),
            *self._misc_xml(),
        ]

        # Wire memory if PCI passthru device is configured
        #   Implicit configuration for now.
        #
        #   To avoid surprising side effects from implicit configuration, wiring of memory
        #   should preferably be an explicit vm configuration option and trigger error
        #   message if not selected when PCI passthru is configured.
        #
        if any(isinstance(device, PCIDevice) for device in self.domain.configuration.devices):
            children.append(xml_element("memoryBacking", children=[xml_element("locked")]))

        return children

    def _os_xml(self) -> ElementTree.Element:
        raise NotImplementedError()

    def _cpu_xml(self) -> list[ElementTree.Element]:
        if self.domain.configuration.vcpus is None and not self.domain.configuration.cpuset:
            return []

        return [
            xml_element(
                "vcpu",
                attributes={"cpuset": self.domain.configuration.cpuset} if self.domain.configuration.cpuset else {},
                text=str((self.domain.configuration.vcpus or 1) *
                         (self.domain.configuration.cores or 1) *
                         (self.domain.configuration.threads or 1))
            )
        ]

    def _memory_xml(self) -> list[ElementTree.Element]:
        return [
            xml_element(
                "memory",
                attributes={"unit": "M"},
                # `<memory>` is required for LXC, so, if it is not specified, just limit it to some absurdly high value
                text=str(self.domain.configuration.memory or 1024 ** 3),
            )
        ]

    def _clock_xml(self) -> ElementTree.Element:
        return xml_element(
            "clock",
            attributes={"offset": "localtime" if self.domain.configuration.time == Time.LOCAL else "utc"},
            children=self._clock_xml_children(),
        )

    def _clock_xml_children(self) -> list[ElementTree.Element]:
        return []

    def _devices_xml(self) -> ElementTree.Element:
        return xml_element("devices", children=self._devices_xml_children())

    def _devices_xml_children(self) -> list[ElementTree.Element]:
        devices = []
        counters = Counters()
        context = DeviceXmlContext(counters)
        for device in self.domain.configuration.devices:
            devices.extend(device.xml(context))

        return devices

    def _features_xml(self) -> ElementTree.Element:
        return xml_element("features", children=self._features_xml_children())

    def _features_xml_children(self) -> list[ElementTree.Element]:
        return []

    def _misc_xml(self) -> list[ElementTree.Element]:
        return []
