from __future__ import annotations

import contextlib
from dataclasses import dataclass
import os
import pathlib
from typing import Any, Generator

import truenas_os
from truenas_os_pyutils.namespace import idmap_userns

from ... import runtime
from ...error import Error
from ..base.domain import BaseDomain
from .configuration import ContainerDomainConfiguration
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

            uid_map = [
                truenas_os.create_idmap_mapping(item.start, item.target, item.count)
                for item in idmap.uid
            ]
            gid_map = [
                truenas_os.create_idmap_mapping(item.start, item.target, item.count)
                for item in idmap.gid
            ]

            tree_fd: int | None = None
            attached = False
            try:
                with idmap_userns(uid_map, gid_map) as userns_fd:
                    tree_fd = truenas_os.open_tree(
                        path=self.configuration.root,
                        flags=truenas_os.OPEN_TREE_CLONE | truenas_os.OPEN_TREE_CLOEXEC,
                    )
                    # Kernel rejects combining MOUNT_ATTR_IDMAP with a
                    # propagation change in a single mount_setattr call,
                    # so apply them in sequence on the still-detached tree.
                    truenas_os.mount_setattr(
                        path="",
                        dirfd=tree_fd,
                        attr_set=truenas_os.MOUNT_ATTR_IDMAP,
                        userns_fd=userns_fd,
                        flags=truenas_os.AT_EMPTY_PATH,
                    )
                    truenas_os.mount_setattr(
                        path="",
                        dirfd=tree_fd,
                        propagation=truenas_os.MS_SLAVE,
                        flags=truenas_os.AT_EMPTY_PATH,
                    )
                    truenas_os.move_mount(
                        from_path="",
                        from_dirfd=tree_fd,
                        to_path=idmapped_root,
                        flags=truenas_os.MOVE_MOUNT_F_EMPTY_PATH,
                    )
                    attached = True
                root = idmapped_root
            except OSError as e:
                raise Error(f"Unable to set up idmapped root: {e}") from None
            finally:
                if tree_fd is not None:
                    os.close(tree_fd)
                if not attached:
                    # Symmetric with FilesystemDevice's failure path: leave no
                    # half-created dir for the startup reconcile to mop up.
                    runtime.cleanup_for_uuid(self.configuration.uuid)

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


@dataclass
class ContainerDomainContext:
    root: str
