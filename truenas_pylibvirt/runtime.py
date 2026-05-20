"""Cleanup and reconciliation of durable runtime state under /run/truenas_containers/.

The container start path stages host-side bind mounts for FilesystemDevice
sources and for the idmap rootfs. Those mounts are durable: they survive a
middleware crash/restart. The Python contextmanager that created them is
in-memory and does not. This module owns reconciling that durable state.

Three call sites use it:

1. FilesystemDevice.run() / ContainerDomain.run() finally blocks -- fast
   happy-path cleanup during a normal stop.
2. DomainManager's STOPPED/UNDEFINED event callback -- authoritative
   cleanup that runs even after a middleware restart, when the in-memory
   started_domains dict is empty.
3. DomainManagers.reconcile_runtime_state() -- one-shot startup sweep.

Mount/umount goes through truenas_os_pyutils.mount.umount (kernel umount2
syscall, with MNT_DETACH fallback on real umount failures). No subprocess
shell-out.

All entry points are idempotent: safe to call repeatedly, safe to call on
UUIDs that have no state, safe to call alongside a freshly starting
container provided the caller passes that UUID in the active set.
"""
from __future__ import annotations

import contextlib
import errno
import logging
import os

from truenas_os_pyutils.mount import iter_mountinfo, umount


logger = logging.getLogger(__name__)


CONTAINERS_RUNTIME_ROOT = "/run/truenas_containers"
DEVICES_RUNTIME_ROOT = os.path.join(CONTAINERS_RUNTIME_ROOT, "devices")
ROOTFS_RUNTIME_ROOT = os.path.join(CONTAINERS_RUNTIME_ROOT, "root")


def cleanup_for_uuid(uuid: str) -> None:
    """Remove every durable runtime artifact for `uuid`. Idempotent."""
    _cleanup_devices_for_uuid(uuid)
    _cleanup_rootfs_for_uuid(uuid)


def reconcile(active_uuids: set[str]) -> None:
    """Sweep runtime state; clean any per-uuid entry not in `active_uuids`.

    Scans both /proc/self/mountinfo (catches mounts whose backing dir was
    removed) and the directory tree (catches empty per-uuid dirs left
    behind by a partially-cleaned shutdown). The union is the set of UUIDs
    needing cleanup.
    """
    orphan_uuids: set[str] = set()

    for mount in iter_mountinfo():
        mountpoint = mount.get("mountpoint")
        if not isinstance(mountpoint, str):
            continue
        uuid = _uuid_from_runtime_path(mountpoint)
        if uuid is None or uuid in active_uuids:
            continue
        orphan_uuids.add(uuid)

    for base in (DEVICES_RUNTIME_ROOT, ROOTFS_RUNTIME_ROOT):
        try:
            with os.scandir(base) as it:
                for entry in it:
                    if entry.name not in active_uuids:
                        orphan_uuids.add(entry.name)
        except FileNotFoundError:
            continue

    for uuid in orphan_uuids:
        logger.info("Reconciling orphaned runtime state for uuid %s", uuid)
        cleanup_for_uuid(uuid)


def umount_and_rmdir(path: str) -> None:
    """Idempotent umount-then-rmdir for a single staged path.

    Lets the kernel be the source of truth: a single umount2() call signals
    "path doesn't exist" (FileNotFoundError), "path isn't a mountpoint"
    (EINVAL), or some real busy/IO failure -- each routed accordingly.
    Pre-checking with os.path.exists + statx would just add TOCTOU windows
    and duplicate syscalls. All failures are best-effort: the caller is one
    of three independent cleanup layers, so a stuck mount here gets a
    retry from the next.
    """
    try:
        umount(path)
    except FileNotFoundError:
        return
    except OSError as e:
        if e.errno != errno.EINVAL:
            logger.warning(
                "Plain umount of %s failed (%s); falling back to MNT_DETACH",
                path,
                e,
            )
            with contextlib.suppress(OSError):
                umount(path, detach=True)
    with contextlib.suppress(OSError):
        os.rmdir(path)


def _uuid_from_runtime_path(path: str) -> str | None:
    """Extract <uuid> from /run/truenas_containers/{devices,root}/<uuid>[/...]."""
    for base in (DEVICES_RUNTIME_ROOT, ROOTFS_RUNTIME_ROOT):
        prefix = base + os.sep
        if path.startswith(prefix):
            remainder = path[len(prefix):]
            uuid = remainder.split(os.sep, 1)[0]
            return uuid or None
    return None


def _cleanup_devices_for_uuid(uuid: str) -> None:
    per_uuid = os.path.join(DEVICES_RUNTIME_ROOT, uuid)
    try:
        with os.scandir(per_uuid) as it:
            for entry in it:
                umount_and_rmdir(entry.path)
    except FileNotFoundError:
        return
    with contextlib.suppress(OSError):
        os.rmdir(per_uuid)


def _cleanup_rootfs_for_uuid(uuid: str) -> None:
    umount_and_rmdir(os.path.join(ROOTFS_RUNTIME_ROOT, uuid))
