import enum

from ..base.configuration import BaseDomainConfiguration


class Bootloader(enum.Enum):
    UEFI = "UEFI"
    UEFI_CSM = "UEFI_CSM"


class CpuMode(enum.Enum):
    CUSTOM = "CUSTOM"
    HOST_MODEL = "HOST-MODEL"
    HOST_PASSTHROUGH = "HOST-PASSTHROUGH"


class VmDomainConfiguration(BaseDomainConfiguration):
    vcpus: int
    cores: int
    threads: int
    memory: int
    arch_type: str
    machine_type: str
    bootloader: Bootloader
    bootloader_ovmf: str
    cpu_mode: CpuMode
    cpu_model: str
    enable_cpu_topology_extension: bool
    nodeset: str | None
    pin_vcpus: bool
    min_memory: int | None
    ensure_display_device: bool
    hyperv_enlightenments: bool
    trusted_platform_module: bool
    hide_from_msr: bool
    enable_secure_boot: bool
    command_line_args: str
    suspend_on_snapshot: bool
