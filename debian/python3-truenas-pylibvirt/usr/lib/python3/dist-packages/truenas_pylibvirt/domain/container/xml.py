import shlex
from typing import TYPE_CHECKING

from ...xml import xml_element
from ..base.xml import BaseDomainXmlGenerator

if TYPE_CHECKING:
    from .domain import ContainerDomain


class ContainerDomainXmlGenerator(BaseDomainXmlGenerator):
    domain: "ContainerDomain"

    def _type(self) -> str:
        return "lxc"

    def _os_xml(self):
        init = shlex.split(self.domain.configuration.init)
        children = [
            xml_element("type", text="exe"),
            xml_element("init", text=init[0]),
        ]
        for arg in init[1:]:
            children.append(xml_element("initarg", text=arg))

        return xml_element("os", children=children)

    def _devices_xml_children(self):
        return [
            *super()._devices_xml_children(),
            xml_element(
                "emulator",
                text="/usr/lib/libvirt/libvirt_lxc",
            ),
            xml_element(
                "console",
                attributes={"type": "pty"},
            ),
            xml_element(
                "filesystem",
                attributes={"type": "mount"},
                children=[
                    xml_element("source", attributes={"dir": self.domain.configuration.root}),
                    xml_element("target", attributes={"dir": "/"}),
                ],
            ),
        ]
