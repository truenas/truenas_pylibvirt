import shlex
from typing import TYPE_CHECKING

from ...xml import xml_element
from ..base.xml import BaseDomainXmlGenerator
from ...device.gpu import GPUDevice


if TYPE_CHECKING:
    from .domain import ContainerDomain, ContainerDomainContext


class ContainerDomainXmlGenerator(BaseDomainXmlGenerator):
    domain: "ContainerDomain"
    context: "ContainerDomainContext"

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

        if self.domain.configuration.initdir is not None:
            children.append(xml_element("initdir", text=self.domain.configuration.initdir))

        for k, v in self.domain.configuration.initenv.items():
            children.append(xml_element("initenv", attributes={"name": k}, text=v))

        if self.domain.configuration.inituser is not None:
            children.append(xml_element("inituser", text=self.domain.configuration.inituser))

        if self.domain.configuration.initgroup is not None:
            children.append(xml_element("initgroup", text=self.domain.configuration.initgroup))

        return xml_element("os", children=children)

    def _devices_xml_children(self):
        devices_xml = [
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
                    xml_element("source", attributes={"dir": self.context.root}),
                    xml_element("target", attributes={"dir": "/"}),
                ],
            ),
        ]
        # We will have to handle GPU's specially
        # For AMD case, we need to add /dev/kfd once even if multiple GPUs are being specified
        if gpu_device := next((
            device for device in self.domain.configuration.devices
            if isinstance(device, GPUDevice) and device.gpu_type.lower() in ('amd', 'nvidia')
        ), None):
            devices_xml.extend(gpu_device.gpu.driver_xml())

        return devices_xml

    def _features_xml_children(self):
        return [
            xml_element(
                "capabilities",
                attributes={"policy": self.domain.configuration.capabilities_policy.value},
                children=[
                    xml_element(capability, attributes={"state": "on" if state else "off"})
                    for capability, state in self.domain.configuration.capabilities_state.items()
                ],
            ),
        ]

    def _misc_xml(self):
        children = []

        # We always specify `idmap` configuration so that libvirt always enabled `user` namespace.
        idmap = self.domain.configuration.idmap
        children.append(xml_element("idmap", children=[
            xml_element("uid", attributes={
                "start": "0",
                "target": str(self.domain.configuration.idmap.uid.target) if idmap else "0",
                "count": str(self.domain.configuration.idmap.uid.count) if idmap else "4294967295",
            }),
            xml_element("gid", attributes={
                "start": "0",
                "target": str(self.domain.configuration.idmap.gid.target) if idmap else "0",
                "count": str(self.domain.configuration.idmap.gid.count) if idmap else "4294967295",
            }),
        ]))

        return children
