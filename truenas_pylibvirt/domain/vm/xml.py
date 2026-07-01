from __future__ import annotations

import platform
import shlex
from typing import TYPE_CHECKING
from xml.etree import ElementTree

from ...device.display import DisplayDevice, DisplayDeviceType
from ...device.nic import NICDevice
from ...utils import kvm_supported
from ...xml import xml_element
from ..base.xml import BaseDomainXmlGenerator
from .configuration import VmBootloader, VmCpuMode
from ...utils.cpu import get_cpu_model_choices
from ...utils.ovmf import AAVMF_DIR, OVMF_DIR, get_ovmf_vars_file

if TYPE_CHECKING:
    from .domain import VmDomain


class VmDomainXmlGenerator(BaseDomainXmlGenerator):

    domain: VmDomain

    def _type(self) -> str:
        if not kvm_supported():
            return "qemu"
        guest_arch = self.domain.configuration.arch_type
        if not guest_arch:
            return "kvm"
        host_arch = platform.machine()
        if guest_arch == host_arch:
            return "kvm"
        # KVM-x86 accelerates 32-bit guests on 64-bit hosts
        if host_arch == "x86_64" and guest_arch in ("i686", "i386"):
            return "kvm"
        return "qemu"

    def _os_xml(self) -> ElementTree.Element:
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
            bootloader_ovmf = self.domain.configuration.bootloader_ovmf
            is_aarch64 = bootloader_ovmf.startswith('AAVMF_CODE')
            firmware_dir = AAVMF_DIR if is_aarch64 else OVMF_DIR
            # secure='yes' is the x86 SMM-based secure-boot signal -- libvirt
            # only accepts it on q35 machines. On aarch64, secure boot is
            # enforced by the AAVMF firmware variant itself (AAVMF_CODE.ms.fd
            # etc.), so we omit the attribute.
            loader_attrs = {"readonly": "yes", "type": "pflash"}
            if not is_aarch64:
                loader_attrs["secure"] = "yes" if self.domain.configuration.enable_secure_boot else "no"
            children.extend([
                xml_element(
                    "loader",
                    attributes=loader_attrs,
                    text=f"{firmware_dir}/{bootloader_ovmf}",
                ),
                xml_element(
                    "nvram",
                    attributes={"template": template_file}
                    if (
                        template_file := get_ovmf_vars_file(self.domain.configuration.bootloader_ovmf)
                    ) else {},
                    text=self.domain.configuration.nvram_path,
                ),
            ])

        return xml_element("os", children=children)

    def _cpu_xml(self) -> list[ElementTree.Element]:
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
            arch = self.domain.configuration.arch_type or 'x86_64'
            if (model := self.domain.configuration.cpu_model) and model in get_cpu_model_choices().get(arch, {}):
                # Right now this is best effort for the domain to start with specified CPU Model and not fallback
                # However if some features are missing in the host, qemu will right now still start the domain
                # and mark them as missing. We should perhaps make this configurable in the future to control
                # if domain should/should not be started
                cpu_children.append(xml_element(
                    "model",
                    attributes={"fallback": "forbid"},
                    text=model,
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

    def _memory_xml(self) -> list[ElementTree.Element]:
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

    def _clock_xml_children(self) -> list[ElementTree.Element]:
        if self.domain.configuration.hyperv_enlightenments:
            return [
                xml_element(
                    "timer",
                    attributes={"name": "hypervclock", "present": "yes"},
                )
            ]

        return []

    def _pci_expansion_controllers(self) -> list[ElementTree.Element]:
        """Inject PCI expansion controllers for any NIC pinned to a non-zero PCI bus.

        q35 machines (pcie-root) use pcie-root-port; i440fx machines (pci-root)
        use pci-bridge. Machine type is detected from the configuration; an absent
        or unrecognised machine_type is treated as i440fx (QEMU's default).
        """
        needed_buses: set[int] = set()
        for device in self.domain.configuration.devices:
            if isinstance(device, NICDevice) and device.pci_address and device.pci_address.bus > 0:
                needed_buses.add(device.pci_address.bus)

        if not needed_buses:
            return []

        is_q35 = 'q35' in (self.domain.configuration.machine_type or '')

        controllers = []
        for bus in sorted(needed_buses):
            if is_q35:
                controllers.append(xml_element(
                    "controller",
                    attributes={"type": "pci", "model": "pcie-root-port", "index": str(bus)},
                    children=[
                        xml_element("target", attributes={"chassis": str(bus), "port": f"0x{0x10 + bus - 1:x}"}),
                    ],
                ))
            else:
                controllers.append(xml_element(
                    "controller",
                    attributes={"type": "pci", "model": "pci-bridge", "index": str(bus)},
                    children=[
                        xml_element("target", attributes={"chassisNr": str(bus)}),
                    ],
                ))
        return controllers

    def _devices_xml_children(self) -> list[ElementTree.Element]:
        children = list(self._pci_expansion_controllers()) + list(super()._devices_xml_children())

        display_device_available = False
        spice_server_available = False
        for device in self.domain.configuration.devices:
            if isinstance(device, DisplayDevice):
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
            # tpm-crb sits on x86's LPC bus; the aarch64 virt machine has no LPC.
            # libvirt's model attribute accepts 'tpm-tis' for aarch64; libvirt
            # translates it to qemu's tpm-tis-device when emitting the cmdline.
            arch_type = self.domain.configuration.arch_type or 'x86_64'
            tpm_model = 'tpm-tis' if arch_type == 'aarch64' else 'tpm-crb'
            children.append(xml_element(
                "tpm",
                attributes={"model": tpm_model},
                children=[
                    xml_element(
                        "backend", attributes={"type": "emulator", "version": "2.0", "persistent_state": "yes"},
                        children=[xml_element(
                            "source", attributes={"type": "dir", "path": self.domain.configuration.tpm_path},
                        )]
                    ),
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

        return list(children)

    def _features_xml_children(self) -> list[ElementTree.Element]:
        arch_type = self.domain.configuration.arch_type or 'x86_64'

        # aarch64 (virt) accepts <acpi/> but rejects x86-specific feature elements
        # (<apic>, <msrs>, <kvm><hidden>, <hyperv>, <smm>). Secure boot on aarch64
        # is signaled via <loader secure='yes'/> in _os_xml(), not via <smm>.
        if arch_type == 'aarch64':
            return [xml_element("acpi")]

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

    def _misc_xml(self) -> list[ElementTree.Element]:
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
