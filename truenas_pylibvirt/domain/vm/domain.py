import contextlib

from ..base.domain import BaseDomain
from .configuration import VmDomainConfiguration


class VmDomain(BaseDomain):
    configuration: VmDomainConfiguration

    def nvram_path(self):
        return ""  # FIXME

    def pid(self) -> int | None:
        pid_path = f"/var/run/libvirt/qemu/{self.configuration.uuid}.pid"
        with contextlib.suppress(FileNotFoundError):
            # Do not make a stat call to check if file exists or not
            with open(pid_path, 'r') as f:
                return int(f.read())
