"""Tests for run_in_container's pre-flight checks (not-running domain and the
namespace-fd validation), which must fail cleanly and not leak fds."""
from __future__ import annotations

from unittest.mock import Mock

import pytest

import truenas_pylibvirt.nsexec._runner as runner


def _dom(domain_id: int = 1234, name: str = "ct") -> Mock:
    dom = Mock()
    dom.ID.return_value = domain_id
    dom.name.return_value = name
    return dom


def test_not_running_domain_raises_before_opening_namespaces(monkeypatch):
    lxc = Mock()
    monkeypatch.setattr(runner.libvirt_lxc, "lxcOpenNamespace", lxc)
    monkeypatch.setattr(runner, "_move_into_cgroup", Mock())

    with pytest.raises(RuntimeError, match="not running"):
        runner.run_in_container(_dom(domain_id=-1), [], "", True, ["/bin/sh"])

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


def test_no_namespace_fds_raises(monkeypatch):
    monkeypatch.setattr(runner, "_move_into_cgroup", Mock())
    monkeypatch.setattr(runner.libvirt_lxc, "lxcOpenNamespace", Mock(return_value=[5]))
    monkeypatch.setattr(runner, "_split_user_fd", Mock(return_value=(-1, [])))
    monkeypatch.setattr(runner.os, "close", Mock())
    enter = Mock()
    monkeypatch.setattr(runner, "enter_and_exec", enter)

    with pytest.raises(RuntimeError, match="no container namespace"):
        runner.run_in_container(_dom(), [], "", False, ["/bin/sh"])

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
