"""Tests for VM XML generation."""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from truenas_pylibvirt.domain.vm.xml import VmDomainXmlGenerator


def _generator(
    arch_type: str | None = None,
    *,
    hide_from_msr: bool = False,
    hyperv_enlightenments: bool = False,
    enable_secure_boot: bool = False,
    trusted_platform_module: bool = False,
    tpm_path: str = '/tmp/tpm',
    ensure_display_device: bool = False,
    devices: list | None = None,
    min_memory: int | None = None,
) -> VmDomainXmlGenerator:
    config = Mock()
    config.arch_type = arch_type
    config.hide_from_msr = hide_from_msr
    config.hyperv_enlightenments = hyperv_enlightenments
    config.enable_secure_boot = enable_secure_boot
    config.trusted_platform_module = trusted_platform_module
    config.tpm_path = tpm_path
    config.ensure_display_device = ensure_display_device
    config.devices = devices if devices is not None else []
    config.min_memory = min_memory
    domain = Mock()
    domain.configuration = config
    gen = VmDomainXmlGenerator.__new__(VmDomainXmlGenerator)
    gen.domain = domain
    return gen


@pytest.mark.parametrize("kvm,host_arch,guest_arch,expected", [
    # /dev/kvm absent -- always TCG
    (False, "x86_64",  None,       "qemu"),
    (False, "x86_64",  "x86_64",   "qemu"),
    (False, "aarch64", "aarch64",  "qemu"),
    # arch_type unset -- host arch implied, KVM
    (True,  "x86_64",  None,       "kvm"),
    (True,  "aarch64", None,       "kvm"),
    # Same arch -- KVM
    (True,  "x86_64",  "x86_64",   "kvm"),
    (True,  "aarch64", "aarch64",  "kvm"),
    # 32-bit x86 guest on 64-bit x86 host -- KVM accelerates this
    (True,  "x86_64",  "i686",     "kvm"),
    (True,  "x86_64",  "i386",     "kvm"),
    # Cross-arch -- TCG
    (True,  "x86_64",  "aarch64",  "qemu"),
    (True,  "aarch64", "x86_64",   "qemu"),
    (True,  "aarch64", "i686",     "qemu"),
])
def test_type_decision(kvm, host_arch, guest_arch, expected):
    """_type() picks kvm for same-arch (or x86 family) when KVM available, qemu otherwise."""
    gen = _generator(guest_arch)
    with patch("truenas_pylibvirt.domain.vm.xml.kvm_supported", return_value=kvm), \
         patch("truenas_pylibvirt.domain.vm.xml.platform.machine", return_value=host_arch):
        assert gen._type() == expected


@pytest.mark.parametrize("arch_type,hide,hyperv,secboot,expected_tags", [
    # x86 baseline (arch_type unset -> defaults to x86_64)
    (None,      False, False, False, ["acpi", "apic", "msrs"]),
    ("x86_64",  False, False, False, ["acpi", "apic", "msrs"]),
    ("i686",    False, False, False, ["acpi", "apic", "msrs"]),
    # x86 with each flag toggled
    ("x86_64",  True,  False, False, ["acpi", "apic", "msrs", "kvm"]),
    ("x86_64",  False, True,  False, ["acpi", "apic", "msrs", "hyperv"]),
    ("x86_64",  False, False, True,  ["acpi", "apic", "msrs", "smm"]),
    ("x86_64",  True,  True,  True,  ["acpi", "apic", "msrs", "kvm", "hyperv", "smm"]),
    # aarch64 emits only <acpi>; x86-only flags are silently dropped at emission
    # (validation tightening is a separate concern). Secure boot on aarch64 is
    # signaled via <loader secure='yes'/> in _os_xml(), not <smm>.
    ("aarch64", False, False, False, ["acpi"]),
    ("aarch64", True,  False, False, ["acpi"]),
    ("aarch64", False, True,  False, ["acpi"]),
    ("aarch64", False, False, True,  ["acpi"]),
    ("aarch64", True,  True,  True,  ["acpi"]),
])
def test_features_xml_children(arch_type, hide, hyperv, secboot, expected_tags):
    """aarch64 emits only <acpi>; x86 emits the full set, flags toggle extra elements."""
    gen = _generator(
        arch_type,
        hide_from_msr=hide,
        hyperv_enlightenments=hyperv,
        enable_secure_boot=secboot,
    )
    assert [f.tag for f in gen._features_xml_children()] == expected_tags


@pytest.mark.parametrize("arch_type,expected_model", [
    (None,      "tpm-crb"),  # default arch = x86_64
    ("x86_64",  "tpm-crb"),
    ("i686",    "tpm-crb"),
    ("aarch64", "tpm-tis"),  # libvirt model name; libvirt emits qemu's tpm-tis-device for it
])
def test_tpm_model(arch_type, expected_model):
    """TPM device model: tpm-crb on x86 (LPC bus); tpm-tis-device on aarch64 (memory-mapped)."""
    gen = _generator(arch_type, trusted_platform_module=True)
    tpm_elements = [d for d in gen._devices_xml_children() if d.tag == "tpm"]
    assert len(tpm_elements) == 1
    assert tpm_elements[0].attrib["model"] == expected_model
