import contextlib
from typing import Any

import libvirt

from ..base.domain import BaseDomain
from .configuration import VmDomainConfiguration
from .xml import VmDomainXmlGenerator


class VmDomain(BaseDomain):
    xml_generator_class = VmDomainXmlGenerator
    configuration: VmDomainConfiguration

    def pid(self) -> int | None:
        pid_path = f"/var/run/libvirt/qemu/{self.configuration.uuid}.pid"
        with contextlib.suppress(FileNotFoundError):
            # Do not make a stat call to check if file exists or not
            with open(pid_path, 'r') as f:
                return int(f.read())
        return None

    def undefine(self, libvirt_domain: Any) -> None:
        libvirt_domain.undefineFlags(libvirt.VIR_DOMAIN_UNDEFINE_KEEP_NVRAM)
        return None
