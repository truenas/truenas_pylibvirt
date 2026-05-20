from __future__ import annotations

import contextlib
from dataclasses import dataclass
import os
import pathlib
import subprocess
from typing import Any, Generator

from ... import runtime
from ...error import Error
from ..base.domain import BaseDomain
from .configuration import ContainerDomainConfiguration, ContainerIdmapConfigurationItem
from .xml import ContainerDomainXmlGenerator


class ContainerDomain(BaseDomain):
    xml_generator_class = ContainerDomainXmlGenerator

    configuration: ContainerDomainConfiguration

    @contextlib.contextmanager
    def run(self) -> Generator[ContainerDomainContext, None, None]:
        root = self.configuration.root
        idmapped_root = None
        if idmap := self.configuration.idmap:
            # Prevent `Failure in libvirt_lxc startup: Failed to create /mnt/tank/container/.oldroot: Permission denied`
            (pathlib.Path(self.configuration.root) / ".oldroot").mkdir(mode=0o0755, exist_ok=True)

            idmapped_root = os.path.join(runtime.ROOTFS_RUNTIME_ROOT, self.configuration.uuid)
            os.makedirs(idmapped_root, exist_ok=True)

            idmap_spec = " ".join(
                [
                    self._x_mount_idmap("u", idmap.uid),
                    self._x_mount_idmap("g", idmap.gid),
                ]
            )
            try:
                subprocess.run(
                    [
                        "mount",
                        "-o",
                        f"bind,X-mount.idmap={idmap_spec}",
                        self.configuration.root,
                        idmapped_root,
                    ],
                    capture_output=True,
                    check=True,
                )
                root = idmapped_root
                # subprocess.run(["mount", "--make-rshared", idmapped_root], capture_output=True, check=True)
            except subprocess.CalledProcessError as e:
                # Symmetric with FilesystemDevice's failure path: leave no
                # half-created dir for the startup reconcile to mop up.
                runtime.cleanup_for_uuid(self.configuration.uuid)
                raise Error(
                    f"Unable to set up idmapped root: {e.cmd} returned code {e.returncode}:\n{e.stderr.strip()}"
                ) from None

        try:
            yield ContainerDomainContext(root=root)
        finally:
            if idmapped_root is not None:
                # Best-effort. The authoritative reconciler is
                # runtime.cleanup_for_uuid (called from the STOPPED event
                # callback in DomainManager), so a failure here must not
                # raise -- otherwise it would mask a more interesting
                # upstream error and prevent siblings' cleanup.
                runtime.umount_and_rmdir(idmapped_root)

    def pid(self) -> int | None:
        pid_path = f"/var/run/libvirt/lxc/{self.configuration.uuid}.pid"
        with contextlib.suppress(FileNotFoundError):
            # Do not make a stat call to check if file exists or not
            with open(pid_path, "r") as f:
                pid = int(f.read())

            with open(f"/proc/{pid}/task/{pid}/children") as f:
                return int(f.read().split()[0])
        return None

    def undefine(self, libvirt_domain: Any) -> None:
        libvirt_domain.undefine()

    def _x_mount_idmap(self, prefix: str, items: list[ContainerIdmapConfigurationItem]) -> str:
        return " ".join(f"{prefix}:{item.start}:{item.target}:{item.count}" for item in items)


@dataclass
class ContainerDomainContext:
    root: str
