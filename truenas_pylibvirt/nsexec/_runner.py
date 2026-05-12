"""Shared in-process runner for entering a libvirt-LXC container.

Both the ``python3 -m truenas_pylibvirt.nsexec`` entry point (used by
middleware via :func:`build_argv_for_shell`) and the higher-level
``truenas-nsexec`` CLI funnel through :func:`run_in_container`. Lives
under a leading underscore because it mutates kernel state of the
calling process (cgroup membership, namespace membership) and is
therefore unsafe to call from a multi-threaded daemon.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import libvirt_lxc

from ._native import enter_and_exec

if TYPE_CHECKING:
    import libvirt


def _move_into_cgroup(init_pid: int) -> None:
    """Join the container's unified cgroup so resource limits apply.

    Must run before fork/setns: cgroup membership is process-level state
    that propagates across fork+exec, and the host's cgroup.procs path
    becomes unreachable from inside the container's mount/cgroup
    namespaces. Without this the entered shell escapes every memory /
    CPU / pids / IO limit configured on the container — a fork-bomb in
    the shell becomes a host fork-bomb. Cgroup v2 only — TrueNAS uses v2.
    """
    cg_path = None
    with open(f"/proc/{init_pid}/cgroup") as cgf:
        for line in cgf:
            if line.startswith("0::"):
                cg_path = line.partition("0::")[2].strip()
                break
    if cg_path is None:
        raise RuntimeError(f"no unified cgroup found for pid {init_pid}")
    with open(f"/sys/fs/cgroup{cg_path}/cgroup.procs", "w") as procs:
        procs.write("0\n")


def _split_user_fd(fds: list[int]) -> tuple[int, list[int]]:
    """Return (user_fd, other_fds). user_fd is -1 if libvirt didn't
    return a user-namespace fd (privileged container, no idmap).

    The user fd is separated because the user-ns setns has to happen
    last — it resets cap sets, see :func:`enter_and_exec`. libvirt
    doesn't document the order of the list returned by
    ``virDomainLxcOpenNamespace``, so we identify each fd via its
    ``/proc/self/fd/<fd>`` readlink rather than by position.
    """
    user_fd = -1
    other_fds: list[int] = []
    for fd in fds:
        if os.readlink(f"/proc/self/fd/{fd}").startswith("user:"):
            user_fd = fd
        else:
            other_fds.append(fd)
    return user_fd, other_fds


def run_in_container(
    dom: "libvirt.virDomain",
    drop_names: list[str],
    caps_text: str,
    has_idmap: bool,
    argv: list[str],
) -> int:
    """Enter the container ``dom`` is running in and exec ``argv``.

    Sequence: cgroup join (host-side) -> open ns fds via libvirt ->
    classify user vs non-user fd -> hand to :func:`enter_and_exec`,
    which performs the setns + cap drop + cap set + fork + execv dance.

    :param dom: running libvirt-LXC domain object
    :param drop_names: libcap names (e.g. ``"cap_lease"``) to drop from
        the bounding set after the user-ns switch
    :param caps_text: libcap text spec applied as the effective+permitted
        set after the user-ns switch, or empty string to skip
    :param has_idmap: whether the container uses a user namespace
        (controls the user-ns setns and the in-child setresuid(0))
    :param argv: command to exec; argv[0] is the path
    :returns: exit status of the in-container process (128+signo if
        terminated by signal)
    """
    _move_into_cgroup(dom.ID())

    fds = libvirt_lxc.lxcOpenNamespace(dom, 0)
    user_fd, other_fds = _split_user_fd(fds)

    # Privileged container (no idmap) — skip the user-ns setns so the
    # process keeps host credentials. Close the fd defensively if
    # libvirt unexpectedly returned one.
    if not has_idmap and user_fd >= 0:
        os.close(user_fd)
        user_fd = -1

    return enter_and_exec(user_fd, other_fds, drop_names, caps_text, argv)
