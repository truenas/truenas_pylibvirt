"""Tests for runtime state cleanup and reconciliation."""
from __future__ import annotations

import errno

import pytest

from truenas_pylibvirt import runtime


def _enoent_umount(path: str, **kw: object) -> None:
    """Simulates `umount(path)` when path does not exist."""
    raise FileNotFoundError(errno.ENOENT, "No such file or directory", path)


def _einval_umount(path: str, **kw: object) -> None:
    """Simulates `umount(path)` when path exists but isn't a mountpoint."""
    raise OSError(errno.EINVAL, "Invalid argument")


@pytest.fixture
def fake_state_dirs(tmp_path, monkeypatch):
    """Redirect the runtime state roots to a tmp_path tree, and simulate
    'path is not a mountpoint' for any umount call -- since the dirs we
    create in tests are never real mounts. iter_mountinfo yields nothing
    so reconcile doesn't pick up real system mounts."""
    devices_root = tmp_path / "devices"
    rootfs_root = tmp_path / "root"
    devices_root.mkdir()
    rootfs_root.mkdir()
    monkeypatch.setattr(runtime, "DEVICES_RUNTIME_ROOT", str(devices_root))
    monkeypatch.setattr(runtime, "ROOTFS_RUNTIME_ROOT", str(rootfs_root))
    monkeypatch.setattr(runtime, "umount", _einval_umount)
    monkeypatch.setattr(runtime, "iter_mountinfo", lambda **kw: iter(()))
    return devices_root, rootfs_root


def test_cleanup_for_uuid_noop_when_paths_missing(fake_state_dirs):
    runtime.cleanup_for_uuid("does-not-exist")
    devices_root, rootfs_root = fake_state_dirs
    assert list(devices_root.iterdir()) == []
    assert list(rootfs_root.iterdir()) == []


def test_cleanup_for_uuid_removes_empty_dirs(fake_state_dirs):
    """umount raises EINVAL (not a mount), function still rmdir's the dir."""
    devices_root, rootfs_root = fake_state_dirs
    (devices_root / "uuid-a" / "slug").mkdir(parents=True)
    (rootfs_root / "uuid-a").mkdir()

    runtime.cleanup_for_uuid("uuid-a")

    assert not (devices_root / "uuid-a").exists()
    assert not (rootfs_root / "uuid-a").exists()


def test_cleanup_for_uuid_is_idempotent(fake_state_dirs):
    devices_root, _ = fake_state_dirs
    (devices_root / "uuid-a" / "slug").mkdir(parents=True)

    runtime.cleanup_for_uuid("uuid-a")
    runtime.cleanup_for_uuid("uuid-a")  # second call must not raise

    assert not (devices_root / "uuid-a").exists()


def test_cleanup_for_uuid_leaves_other_uuids_alone(fake_state_dirs):
    devices_root, _ = fake_state_dirs
    (devices_root / "uuid-a" / "slug").mkdir(parents=True)
    (devices_root / "uuid-b" / "slug").mkdir(parents=True)

    runtime.cleanup_for_uuid("uuid-a")

    assert not (devices_root / "uuid-a").exists()
    assert (devices_root / "uuid-b" / "slug").exists()


def test_reconcile_keeps_active_removes_orphans(fake_state_dirs):
    devices_root, rootfs_root = fake_state_dirs
    (devices_root / "active-uuid" / "slug").mkdir(parents=True)
    (devices_root / "orphan-uuid" / "slug").mkdir(parents=True)
    (rootfs_root / "active-uuid").mkdir()
    (rootfs_root / "orphan-uuid").mkdir()

    runtime.reconcile({"active-uuid"})

    assert (devices_root / "active-uuid" / "slug").exists()
    assert (rootfs_root / "active-uuid").exists()
    assert not (devices_root / "orphan-uuid").exists()
    assert not (rootfs_root / "orphan-uuid").exists()


def test_reconcile_handles_missing_base_dirs(tmp_path, monkeypatch):
    """If neither base exists yet (fresh install), reconcile is a no-op."""
    missing_devices = tmp_path / "missing-devices"
    missing_rootfs = tmp_path / "missing-rootfs"
    monkeypatch.setattr(runtime, "DEVICES_RUNTIME_ROOT", str(missing_devices))
    monkeypatch.setattr(runtime, "ROOTFS_RUNTIME_ROOT", str(missing_rootfs))
    monkeypatch.setattr(runtime, "iter_mountinfo", lambda **kw: iter(()))

    runtime.reconcile({"any-uuid"})  # must not raise


def test_reconcile_with_empty_active_set_cleans_everything(fake_state_dirs):
    devices_root, rootfs_root = fake_state_dirs
    (devices_root / "uuid-a" / "slug").mkdir(parents=True)
    (rootfs_root / "uuid-b").mkdir()

    runtime.reconcile(set())

    assert not (devices_root / "uuid-a").exists()
    assert not (rootfs_root / "uuid-b").exists()


def test_reconcile_finds_orphan_via_mountinfo_when_dir_is_gone(
    tmp_path, monkeypatch,
):
    """A mount that survives without its parent dir is detected via
    iter_mountinfo and triggers cleanup_for_uuid for that UUID."""
    devices_root = tmp_path / "devices"
    rootfs_root = tmp_path / "root"
    devices_root.mkdir()
    rootfs_root.mkdir()
    monkeypatch.setattr(runtime, "DEVICES_RUNTIME_ROOT", str(devices_root))
    monkeypatch.setattr(runtime, "ROOTFS_RUNTIME_ROOT", str(rootfs_root))

    stale_mountpoint = f"{devices_root}/ghost-uuid/%2Fmnt%2Fghost"
    monkeypatch.setattr(
        runtime, "iter_mountinfo",
        lambda **kw: iter([{"mountpoint": stale_mountpoint}]),
    )

    calls: list[str] = []
    monkeypatch.setattr(runtime, "cleanup_for_uuid", lambda u: calls.append(u))

    runtime.reconcile(set())

    assert "ghost-uuid" in calls


def test_reconcile_ignores_unrelated_mountinfo_entries(
    tmp_path, monkeypatch,
):
    devices_root = tmp_path / "devices"
    rootfs_root = tmp_path / "root"
    devices_root.mkdir()
    rootfs_root.mkdir()
    monkeypatch.setattr(runtime, "DEVICES_RUNTIME_ROOT", str(devices_root))
    monkeypatch.setattr(runtime, "ROOTFS_RUNTIME_ROOT", str(rootfs_root))
    monkeypatch.setattr(
        runtime, "iter_mountinfo",
        lambda **kw: iter([
            {"mountpoint": "/"},
            {"mountpoint": "/proc"},
            {"mountpoint": "/mnt/tank"},
            {"mountpoint": None},
        ]),
    )

    calls: list[str] = []
    monkeypatch.setattr(runtime, "cleanup_for_uuid", lambda u: calls.append(u))

    runtime.reconcile(set())

    assert calls == []


def test_uuid_from_runtime_path():
    assert runtime._uuid_from_runtime_path(
        "/run/truenas_containers/devices/aaa/slug"
    ) == "aaa"
    assert runtime._uuid_from_runtime_path(
        "/run/truenas_containers/root/bbb"
    ) == "bbb"
    assert runtime._uuid_from_runtime_path("/mnt/tank") is None
    assert runtime._uuid_from_runtime_path("/run/truenas_containers/devices") is None


def test_umount_and_rmdir_path_missing_is_noop(tmp_path, monkeypatch):
    """umount raises FileNotFoundError -> function returns without rmdir."""
    monkeypatch.setattr(runtime, "umount", _enoent_umount)
    runtime.umount_and_rmdir(str(tmp_path / "never-existed"))


def test_umount_and_rmdir_not_a_mount_still_rmdirs(tmp_path, monkeypatch):
    """umount raises EINVAL (path exists, not a mount) -> rmdir runs."""
    path = tmp_path / "stage"
    path.mkdir()
    monkeypatch.setattr(runtime, "umount", _einval_umount)

    runtime.umount_and_rmdir(str(path))

    assert not path.exists()


def test_umount_and_rmdir_falls_back_to_detach_on_other_errors(tmp_path, monkeypatch):
    """A non-EINVAL umount failure (e.g. EBUSY) triggers detach=True retry."""
    path = tmp_path / "stage"
    path.mkdir()

    calls: list[dict] = []

    def fake_umount(p, **kw):
        calls.append({"path": p, **kw})
        if not kw.get("detach"):
            raise OSError(errno.EBUSY, "Device or resource busy")

    monkeypatch.setattr(runtime, "umount", fake_umount)

    runtime.umount_and_rmdir(str(path))

    assert len(calls) == 2
    assert calls[0] == {"path": str(path)}
    assert calls[1] == {"path": str(path), "detach": True}
