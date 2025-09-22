import contextlib
from dataclasses import dataclass
import os
import pathlib
import subprocess

from ...error import Error
from ..base.domain import BaseDomain
from .configuration import ContainerDomainConfiguration, ContainerIdmapConfigurationItem
from .xml import ContainerDomainXmlGenerator


class ContainerDomain(BaseDomain):
    xml_generator_class = ContainerDomainXmlGenerator

    configuration: ContainerDomainConfiguration

    @contextlib.contextmanager
    def run(self):
        root = self.configuration.root
        idmapped_root = None
        if idmap := self.configuration.idmap:
            # Prevent `Failure in libvirt_lxc startup: Failed to create /mnt/tank/container/.oldroot: Permission denied`
            (pathlib.Path(self.configuration.root) / ".oldroot").mkdir(mode=0o0755, exist_ok=True)

            idmapped_root = f"/run/truenas_containers/root/{self.configuration.uuid}"
            os.makedirs(idmapped_root, exist_ok=True)

            try:
                subprocess.run([
                    "mount",
                    "-o", f"bind,X-mount.idmap=u:{self._x_mount_idmap(idmap.uid)} g:{self._x_mount_idmap(idmap.gid)}",
                    self.configuration.root,
                    idmapped_root,
                ], capture_output=True, check=True)
                root = idmapped_root
                # subprocess.run(["mount", "--make-rshared", idmapped_root], capture_output=True, check=True)
            except subprocess.CalledProcessError as e:
                raise Error(
                    f"Unable to set up idmapped root: {e.cmd} returned code {e.returncode}:\n{e.stderr.strip()}"
                ) from None

        try:
            yield ContainerDomainContext(root=root)
        finally:
            if idmapped_root is not None:
                try:
                    subprocess.run(["umount", idmapped_root], capture_output=True, check=True)
                except subprocess.CalledProcessError as e:
                    raise Error(
                        f"Unable to umount idmapped root: {e.cmd} returned code {e.returncode}:\n{e.stderr.strip()}"
                    ) from None

                os.rmdir(idmapped_root)

    def pid(self) -> int | None:
        pid_path = f"/var/run/libvirt/lxc/{self.configuration.uuid}.pid"
        with contextlib.suppress(FileNotFoundError):
            # Do not make a stat call to check if file exists or not
            with open(pid_path, 'r') as f:
                pid = int(f.read())

            with open(f'/proc/{pid}/task/{pid}/children') as f:
                return int(f.read().split()[0])

    def _x_mount_idmap(self, item: ContainerIdmapConfigurationItem):
        return f"0:{item.target}:{item.count}"


@dataclass
class ContainerDomainContext:
    root: str
