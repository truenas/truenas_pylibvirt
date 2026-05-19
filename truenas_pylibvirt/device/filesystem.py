from __future__ import annotations

import contextlib
import os
import urllib.parse
from dataclasses import dataclass
from typing import Generator, TYPE_CHECKING
from xml.etree import ElementTree

import truenas_os

from .base import Device, DeviceXmlContext
from ..error import Error
from ..runtime import DEVICES_RUNTIME_ROOT, umount_and_rmdir
from ..xml import xml_element

if TYPE_CHECKING:
    from ..libvirtd.connection import Connection


@dataclass(kw_only=True)
class FilesystemDevice(Device):

    target: str
    source: str

    def xml(self, context: DeviceXmlContext) -> list[ElementTree.Element]:
        return [
            xml_element(
                'filesystem',
                attributes={'type': 'mount'},
                children=[
                    xml_element('source', attributes={'dir': self.source}),
                    xml_element('target', attributes={'dir': self.target}),
                ],
            ),
        ]

    @contextlib.contextmanager
    def run(
        self, connection: "Connection", domain_uuid: str,
    ) -> Generator[None, None, None]:
        # Stage a host-side, non-recursive clone of `self.source` onto a
        # per-device path under /run, with slave propagation, then redirect
        # `self.source` to that staged path so xml() emits it.
        #
        # libvirt-LXC hard-codes a non-recursive MS_BIND for FILESYSTEM
        # devices (src/lxc/lxc_container.c:lxcContainerMountFSBind) and runs
        # it inside the container's user namespace. If the user-supplied
        # source has nested submounts -- typical for a ZFS parent dataset
        # with auto-mounted children -- the kernel's has_locked_children
        # check in fs/namespace.c:__do_loopback rejects the bind with
        # EINVAL because those children propagated into the less-privileged
        # userns are marked locked (kernel commit 5ff9d8a65ce8). Staging
        # here, as host root in init_user_ns, gives libvirt a single flat
        # mount with no children.
        #
        # As a side effect this also fixes ENOENT path-traversal failures
        # when the user's source has a restrictive parent ACL, because the
        # mapped UID's access check now runs against a middleware-owned
        # /run path.
        #
        # Implementation: open_tree(OPEN_TREE_CLONE) clones the source mount
        # as a detached tree, mount_setattr applies MS_SLAVE propagation
        # while detached, and move_mount attaches the clone at staged_path.
        # Applying propagation before attach closes the window the old
        # `mount --bind` + `mount --make-rslave` pair had, where the staged
        # mount briefly inherited shared propagation from the source.
        # AT_RECURSIVE on mount_setattr is a no-op today (the clone is
        # non-recursive, no children) but auto-covers children if the clone
        # ever switches to OPEN_TREE_CLONE | AT_RECURSIVE.
        #
        # The finally below only undoes this device's own staging. The
        # per-uuid parent dir and any leftovers across a middleware restart
        # are reaped by truenas_pylibvirt.runtime.cleanup_for_uuid, called
        # from DomainManager's STOPPED/UNDEFINED event callback.
        original_source = self.source
        staged_path = os.path.join(
            DEVICES_RUNTIME_ROOT, domain_uuid, self._staging_slug(),
        )

        os.makedirs(staged_path, mode=0o755, exist_ok=True)

        fd: int | None = None
        attached = False
        try:
            fd = truenas_os.open_tree(
                path=original_source,
                flags=truenas_os.OPEN_TREE_CLONE | truenas_os.OPEN_TREE_CLOEXEC,
            )
            truenas_os.mount_setattr(
                path="",
                dirfd=fd,
                propagation=truenas_os.MS_SLAVE,
                flags=truenas_os.AT_EMPTY_PATH | truenas_os.AT_RECURSIVE,
            )
            truenas_os.move_mount(
                from_path="",
                from_dirfd=fd,
                to_path=staged_path,
                flags=truenas_os.MOVE_MOUNT_F_EMPTY_PATH,
            )
            attached = True
        except OSError as e:
            raise Error(
                f"Unable to stage filesystem device {self.identity()!r}: {e}"
            ) from None
        finally:
            if fd is not None:
                os.close(fd)
            if not attached:
                self._cleanup_self_stage(staged_path)

        self.source = staged_path
        try:
            yield
        finally:
            self.source = original_source
            self._cleanup_self_stage(staged_path)

    def _staging_slug(self) -> str:
        return urllib.parse.quote(self.target, safe='')

    @staticmethod
    def _cleanup_self_stage(staged_path: str) -> None:
        # Best-effort: only undo this device's own mount + dir. The per-uuid
        # parent dir is left for runtime.cleanup_for_uuid to reap centrally.
        umount_and_rmdir(staged_path)

    def identity_impl(self) -> str:
        return f'{self.source}:{self.target}'

    def is_available_impl(self) -> bool:
        return os.path.exists(self.source)

    def validate_impl(self) -> list[tuple[str, str]]:
        verrors = []
        if self.target == '/':
            verrors.append(('target', 'Target can\'t be root'))
        elif not os.path.isabs(self.target):
            verrors.append(('target', 'Target must be an absolute path'))
        if self.source == '/':
            verrors.append(('source', 'Source can\'t be root'))
        elif not os.path.isabs(self.source):
            verrors.append(('source', 'Source must be an absolute path'))
        elif not os.path.exists(self.source):
            verrors.append(('source', f'Source {self.source} does not exist'))
        return verrors
