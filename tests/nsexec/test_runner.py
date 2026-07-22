"""Tests for run_in_container's pre-flight checks (not-running domain and the
namespace-fd validation), which must fail cleanly and not leak fds."""
from __future__ import annotations

import os
from unittest.mock import Mock

import pytest

import truenas_pylibvirt.nsexec._runner as runner


def _dom(domain_id: int = 1234, name: str = "ct") -> Mock:
    dom = Mock()
    dom.ID.return_value = domain_id
    dom.name.return_value = name
    return dom


def test_split_user_fd_classifies_real_fds():
    """The user-ns fd is found by readlink'ing /proc/self/fd/<n>, not by its
    position in the list libvirt returns (which is undocumented)."""
    fds = [
        os.open("/proc/self/ns/uts", os.O_RDONLY),
        os.open("/proc/self/ns/user", os.O_RDONLY),
        os.open("/proc/self/ns/ipc", os.O_RDONLY),
    ]
    try:
        user_fd, other_fds = runner._split_user_fd(fds)
        assert user_fd == fds[1]
        assert other_fds == [fds[0], fds[2]]
    finally:
        for fd in fds:
            os.close(fd)


def test_not_running_domain_raises_before_touching_the_container(monkeypatch):
    move = Mock()
    lxc = Mock()
    monkeypatch.setattr(runner, "_move_into_cgroup", move)
    monkeypatch.setattr(runner.libvirt_lxc, "lxcOpenNamespace", lxc)

    with pytest.raises(RuntimeError, match="not running"):
        runner.run_in_container(_dom(domain_id=-1), [], "", True, ["/bin/sh"])

    # The bug being guarded: ID() == -1 fell through to _move_into_cgroup(-1),
    # which opened /proc/-1/cgroup. Asserting only on lxcOpenNamespace would
    # still pass with the check moved back below the cgroup join.
    move.assert_not_called()
    lxc.assert_not_called()


def test_idmap_without_user_fd_raises_and_closes_all_fds(monkeypatch):
    closed: list[int] = []
    monkeypatch.setattr(runner, "_move_into_cgroup", Mock())
    monkeypatch.setattr(runner.libvirt_lxc, "lxcOpenNamespace", Mock(return_value=[7, 8, 9]))
    monkeypatch.setattr(runner, "_split_user_fd", Mock(return_value=(-1, [8, 9])))
    monkeypatch.setattr(runner.os, "close", closed.append)
    enter = Mock()
    monkeypatch.setattr(runner, "enter_and_exec", enter)

    with pytest.raises(RuntimeError, match="user namespace"):
        runner.run_in_container(_dom(), [], "", True, ["/bin/sh"])

    assert sorted(closed) == [7, 8, 9]  # every fd libvirt returned is closed
    enter.assert_not_called()


def test_only_user_fd_returned_raises_and_closes_it(monkeypatch):
    # A reachable shape: libvirt hands back a user-ns fd and nothing else, so
    # _split_user_fd leaves other_fds empty and there is nothing to setns into.
    closed: list[int] = []
    monkeypatch.setattr(runner, "_move_into_cgroup", Mock())
    monkeypatch.setattr(runner.libvirt_lxc, "lxcOpenNamespace", Mock(return_value=[5]))
    monkeypatch.setattr(runner, "_split_user_fd", Mock(return_value=(5, [])))
    monkeypatch.setattr(runner.os, "close", closed.append)
    enter = Mock()
    monkeypatch.setattr(runner, "enter_and_exec", enter)

    with pytest.raises(RuntimeError, match="no container namespace"):
        runner.run_in_container(_dom(), [], "", False, ["/bin/sh"])

    assert closed == [5]
    enter.assert_not_called()


def test_happy_path_idmap_forwards_fds(monkeypatch):
    monkeypatch.setattr(runner, "_move_into_cgroup", Mock())
    monkeypatch.setattr(runner.libvirt_lxc, "lxcOpenNamespace", Mock(return_value=[3, 4, 5]))
    monkeypatch.setattr(runner, "_split_user_fd", Mock(return_value=(3, [4, 5])))
    enter = Mock(return_value=42)
    monkeypatch.setattr(runner, "enter_and_exec", enter)

    rc = runner.run_in_container(_dom(), ["cap_lease"], "cap_net_admin+ep", True, ["/bin/sh"])

    assert rc == 42
    enter.assert_called_once_with(3, [4, 5], ["cap_lease"], "cap_net_admin+ep", ["/bin/sh"])


def test_privileged_closes_stray_user_fd(monkeypatch):
    closed: list[int] = []
    monkeypatch.setattr(runner, "_move_into_cgroup", Mock())
    monkeypatch.setattr(runner.libvirt_lxc, "lxcOpenNamespace", Mock(return_value=[3, 4, 5]))
    monkeypatch.setattr(runner, "_split_user_fd", Mock(return_value=(3, [4, 5])))
    monkeypatch.setattr(runner.os, "close", closed.append)
    enter = Mock(return_value=0)
    monkeypatch.setattr(runner, "enter_and_exec", enter)

    runner.run_in_container(_dom(), [], "", False, ["/bin/sh"])  # has_idmap=False

    assert closed == [3]  # stray user-ns fd dropped for a privileged container
    enter.assert_called_once_with(-1, [4, 5], [], "", ["/bin/sh"])
