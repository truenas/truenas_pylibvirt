from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from ...device.display import DisplayDevice, DisplayDeviceType
from ...xml import xml_element
from ..base.xml import BaseDomainXmlGenerator
from .configuration import VmBootloader, VmCpuMode
from ...utils.cpu import get_cpu_model_choices

if TYPE_CHECKING:
    from .domain import VmDomain


class VmDomainXmlGenerator(BaseDomainXmlGenerator):

    domain: VmDomain

    def _type(self) -> str:
        return "kvm"

    def _os_xml(self):
        hvm_attributes = {}
        if self.domain.configuration.arch_type:
            hvm_attributes["arch"] = self.domain.configuration.arch_type
        if self.domain.configuration.machine_type:
            hvm_attributes["machine"] = self.domain.configuration.machine_type

        children = [
            xml_element(
                "type",
                attributes=hvm_attributes,
                text="hvm",
            )
        ]

        if self.domain.configuration.bootloader == VmBootloader.UEFI:
            children.extend([
                xml_element(
                    "loader",
                    attributes={
                        "readonly": "yes",
                        "secure": "yes" if self.domain.configuration.enable_secure_boot else "no",
                        "type": "pflash",
                    },
                    text=f"/usr/share/OVMF/{self.domain.configuration.bootloader_ovmf}",
                ),
                xml_element(
                    "nvram",
                    text=self.domain.configuration.nvram_path,
                ),
            ])

        return xml_element("os", children=children)

    def _cpu_xml(self):
        children = super()._cpu_xml()

        cpu_children = []

        cpu_children.append(xml_element(
            "topology",
            attributes={
                "sockets": str(self.domain.configuration.vcpus),
                "cores": str(self.domain.configuration.cores),
                "threads": str(self.domain.configuration.threads),
            },
        ))

        if self.domain.configuration.cpu_mode == VmCpuMode.CUSTOM:
            if self.domain.configuration.cpu_model and get_cpu_model_choices(self.domain.configuration.cpu_model):
                # Right now this is best effort for the domain to start with specified CPU Model and not fallback
                # However if some features are missing in the host, qemu will right now still start the domain
                # and mark them as missing. We should perhaps make this configurable in the future to control
                # if domain should/should not be started
                cpu_children.append(xml_element(
                    "model",
                    attributes={"fallback": "forbid"},
                    text=self.domain.configuration.cpu_model,
                ))

        if self.domain.configuration.cpu_mode == VmCpuMode.HOST_PASSTHROUGH:
            cpu_children.append(xml_element("cache", attributes={"mode": "passthrough"}))
            if self.domain.configuration.enable_cpu_topology_extension:
                cpu_children.append(xml_element("feature", attributes={"name": "topoext", "policy": "require"}))

        children.append(xml_element(
            "cpu",
            attributes={"mode": self.domain.configuration.cpu_mode.value.lower()},
            children=cpu_children,
        ))

        if self.domain.configuration.cpuset and self.domain.configuration.pin_vcpus:
            children.append(xml_element(
                "cputune",
                children=[
                    xml_element(
                        "vcpupin",
                        attributes={"vcpu": str(i), "cpuset": str(cpu)},
                    )
                    for i, cpu in enumerate(self.domain.configuration.cpuset_list)
                ]
            ))

        if self.domain.configuration.nodeset:
            children.append(xml_element(
                "numatune",
                children=[
                    xml_element(
                        "memory",
                        attributes={"nodeset": self.domain.configuration.nodeset},
                    )
                ]
            ))

        return children

    def _memory_xml(self):
        children = super()._memory_xml()

        # Memory Ballooning - this will be memory which will always be allocated to the VM
        # If not specified, this defaults to `memory`
        if self.domain.configuration.min_memory:
            children.append(
                xml_element(
                    "currentMemory",
                    attributes={"unit": "M"},
                    text=str(self.domain.configuration.min_memory),
                )
            )

        return children

    def _clock_xml_children(self):
        if self.domain.configuration.hyperv_enlightenments:
            return [
                xml_element(
                    "timer",
                    attributes={"name": "hypervclock", "present": "yes"},
                )
            ]

        return []

    def _devices_xml_children(self):
        children = super()._devices_xml_children()

        display_device_available = False
        spice_server_available = False
        for device in filter(lambda d: isinstance(d, DisplayDevice), self.domain.configuration.devices):
            display_device_available = True
            if device.type_ == DisplayDeviceType.SPICE:
                spice_server_available = True
                break

        if self.domain.configuration.ensure_display_device and not display_device_available:
            # We should add a video device if there is no display device configured because most by
            # default if not all headless servers like ubuntu etc require it to boot
            children.append(xml_element("video"))

        if spice_server_available:
            # We always add spicevmc channel device when a spice display device is available to allow users
            # to install guest agents for improved vm experience
            children.append(xml_element(
                "channel",
                attributes={"type": "spicevmc"},
                children=[xml_element("target", attributes={"type": "virtio", "name": "com.redhat.spice.0"})],
            ))

        if self.domain.configuration.trusted_platform_module:
            children.append(xml_element(
                "tpm",
                attributes={"model": "tpm-crb"},
                children=[
                    xml_element("backend", attributes={"type": "emulator", "version": "2.0"}),
                ],
            ))

        children.append(xml_element(
            "channel",
            attributes={"type": "unix"},
            children=[
                xml_element("target", attributes={"type": "virtio", "name": "org.qemu.guest_agent.0"}),
            ],
        ))
        children.append(xml_element(
            "serial",
            attributes={"type": "pty"},
        ))

        if self.domain.configuration.min_memory:
            children.append(xml_element(
                "memballoon",
                attributes={"model": "virtio", "autodeflate": "on"},
            ))

        return children

    def _features_xml_children(self):
        features = [
            xml_element("acpi"),
            xml_element("apic"),
            xml_element("msrs", attributes={"unknown": "ignore"}),
        ]

        if self.domain.configuration.hide_from_msr:
            features.append(xml_element(
                "kvm",
                children=[xml_element("hidden", attributes={"state": "on"})],
            ))

        if self.domain.configuration.hyperv_enlightenments:
            # Documentation for each enlightenment can be found from:
            # https://github.com/qemu/qemu/blob/master/docs/system/i386/hyperv.rst
            features.append(xml_element(
                "hyperv",
                children=[
                    xml_element("relaxed", attributes={"state": "on"}),
                    xml_element("vapic", attributes={"state": "on"}),
                    xml_element("spinlocks", attributes={"state": "on", "retries": "8191"}),
                    xml_element("reset", attributes={"state": "on"}),
                    xml_element("frequencies", attributes={"state": "on"}),
                    # All enlightenments under vpindex depend on it.
                    xml_element("vpindex", attributes={"state": "on"}),
                    xml_element("synic", attributes={"state": "on"}),
                    xml_element("ipi", attributes={"state": "on"}),
                    xml_element("tlbflush", attributes={"state": "on"}),
                    xml_element("stimer", attributes={"state": "on"})
                ],
            ))

        if self.domain.configuration.enable_secure_boot:
            features.append(xml_element("smm", attributes={"state": "on"}))

        return features

    def _misc_xml(self):
        return [
            xml_element(
                "commandline",
                attributes={"xmlns": "http://libvirt.org/schemas/domain/qemu/1.0"},
                children=[
                    xml_element("arg", attributes={"value": arg})
                    for arg in shlex.split(self.domain.configuration.command_line_args)
                ],
            ),
        ]
