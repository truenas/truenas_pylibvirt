"""Enter an already-running libvirt-LXC container as a child process with
the configured capability restrictions applied.

.. warning::

   The C primitives in this package — :func:`enter_and_exec`, :func:`setns`,
   :func:`drop_bounding`, :func:`cap_set_proc_from_text` — mutate kernel
   state of the **calling process**: namespace membership, capability
   bounding set (drops are irreversible), effective/permitted cap sets,
   and (for :func:`enter_and_exec`) fork a child. They are safe for a
   single-purpose subprocess to call, and are **unsafe** to call from a
   persistent multi-threaded daemon like middlewared directly:

   * ``setns(CLONE_NEWUSER)`` fails with EINVAL on multi-threaded callers
     (see setns(2)); middlewared has many worker threads.
   * ``prctl(PR_CAPBSET_DROP)`` is irreversible — calling it from the
     daemon permanently degrades the daemon's own privileges.
   * ``enter_and_exec`` forks the caller; forking a multi-threaded process
     is a well-known footgun (post-fork state of other threads is
     undefined).

   The sanctioned invocation is via the subprocess entry point
   ``python3 -m truenas_pylibvirt.nsexec`` (see :func:`build_argv_for_shell`).
   Everything else in this module — :func:`build_argv_for_shell`,
   :data:`ALL_CAPABILITIES`, :data:`DEFAULT_POLICY_DROPS`, the
   ``CLONE_NEW*`` constants — is pure Python/data and safe to import
   from middleware.

Namespace fds come from libvirt (``virDomainLxcOpenNamespace``, exposed in
Python as ``libvirt_lxc.lxcOpenNamespace``) rather than from a manual walk
over ``/proc/<pid>/ns/*``. This removes the PID-reuse race between the
host-side lookup and the setns sequence, and keeps the package decoupled
from proc-fs layout assumptions.

Ordering invariant: setns(CLONE_NEWUSER) resets every capability set, so
drops and the explicit effective+permitted set MUST be applied between the
user-namespace switch and the rest of the setns calls. The composite
:func:`enter_and_exec` handles this sequencing in C; the individual
primitives are exposed for callers that need finer control.
"""

import sys

from ._native import (
    CLONE_NEWIPC,
    CLONE_NEWNET,
    CLONE_NEWNS,
    CLONE_NEWPID,
    CLONE_NEWUSER,
    CLONE_NEWUTS,
    cap_from_name,
    cap_set_proc_from_text,
    drop_bounding,
    enter_and_exec,
    setns,
)


__all__ = [
    "ALL_CAPABILITIES",
    "CLONE_NEWIPC",
    "CLONE_NEWNET",
    "CLONE_NEWNS",
    "CLONE_NEWPID",
    "CLONE_NEWUSER",
    "CLONE_NEWUTS",
    "DEFAULT_POLICY_DROPS",
    "build_argv_for_shell",
    "cap_from_name",
    "cap_set_proc_from_text",
    "drop_bounding",
    "enter_and_exec",
    "setns",
]


# Capabilities libvirtd's lxc driver drops by default before starting the
# container. Kept here so consumers that want the same "default" policy in
# the context of opening a shell can share the single source of truth.
DEFAULT_POLICY_DROPS = ("sys_module", "sys_time", "mknod", "audit_control", "mac_admin")


# Every capability name currently known (matches capabilities(7)).
ALL_CAPABILITIES = frozenset(
    [
        "chown",
        "dac_override",
        "dac_read_search",
        "fowner",
        "fsetid",
        "kill",
        "setgid",
        "setuid",
        "setpcap",
        "linux_immutable",
        "net_bind_service",
        "net_broadcast",
        "net_admin",
        "net_raw",
        "ipc_lock",
        "ipc_owner",
        "sys_module",
        "sys_rawio",
        "sys_chroot",
        "sys_ptrace",
        "sys_pacct",
        "sys_admin",
        "sys_boot",
        "sys_nice",
        "sys_resource",
        "sys_time",
        "sys_tty_config",
        "mknod",
        "lease",
        "audit_write",
        "audit_control",
        "setfcap",
        "mac_override",
        "mac_admin",
        "syslog",
        "wake_alarm",
        "block_suspend",
        "audit_read",
        "perfmon",
        "bpf",
        "checkpoint_restore",
    ]
)


def _derive_caps(policy: str, capabilities_state: dict):
    """Return (drop_names, enabled_names) from the raw policy + state."""
    policy = policy.upper()
    if policy == "DEFAULT":
        drop = [
            n for n in DEFAULT_POLICY_DROPS if capabilities_state.get(n) is not True
        ]
        drop += [n for n, on in capabilities_state.items() if not on]
    elif policy == "ALLOW":
        drop = [n for n, on in capabilities_state.items() if not on]
    elif policy == "DENY":
        drop = [n for n in ALL_CAPABILITIES if capabilities_state.get(n) is not True]
    else:
        raise ValueError(f"unknown capabilities policy: {policy!r}")

    enabled = [n for n, on in capabilities_state.items() if on]
    return drop, enabled


def build_argv_for_shell(
    uuid, uri, capabilities_policy, capabilities_state, has_idmap, shell_argv
):
    """Build the argv to hand to execve(2) for opening a shell in a
    running container.

    Returns a list that invokes ``python3 -m truenas_pylibvirt.nsexec``, which
    in turn connects to libvirt, calls :func:`libvirt_lxc.lxcOpenNamespace`
    to get the container's namespace fds, and hands them to
    :func:`enter_and_exec`. Keeping the policy-to-argv translation here keeps
    middleware consumers decoupled from the wire format.

    :param uuid: libvirt domain UUID (string) for the target container
    :param uri: libvirt connection URI (e.g. "lxc:///system?socket=...")
    :param capabilities_policy: "DEFAULT" | "ALLOW" | "DENY" (case-insensitive)
    :param capabilities_state: dict[str, bool] — explicit overrides
    :param has_idmap: whether the container uses a user namespace (--user)
    :param shell_argv: argv of the shell to launch inside the container
                       (e.g. ["/bin/sh", "-c", cmd])
    """
    drop_names, enabled = _derive_caps(capabilities_policy, capabilities_state)
    drop_csv = ",".join(f"cap_{n}" for n in drop_names)
    caps_text = f"{','.join(f'cap_{n}' for n in enabled)}+ep" if enabled else ""
    return [
        sys.executable,
        "-m",
        "truenas_pylibvirt.nsexec",
        uri,
        uuid,
        drop_csv,
        caps_text,
        "1" if has_idmap else "0",
    ] + list(shell_argv)
