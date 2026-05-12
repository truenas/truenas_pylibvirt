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
from types import MappingProxyType

from ._native import (
    CLONE_NEWIPC,
    CLONE_NEWNET,
    CLONE_NEWNS,
    CLONE_NEWPID,
    CLONE_NEWUSER,
    CLONE_NEWUTS,
    cap_from_name,
    cap_max_bits,
    cap_set_proc_from_text,
    cap_to_name,
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
    "cap_max_bits",
    "cap_set_proc_from_text",
    "cap_to_name",
    "derive_caps",
    "drop_bounding",
    "enter_and_exec",
    "setns",
]


# Capabilities libvirtd's lxc driver drops by default before starting the
# container. Kept here so consumers that want the same "default" policy in
# the context of opening a shell can share the single source of truth.
DEFAULT_POLICY_DROPS = ("sys_module", "sys_time", "mknod", "audit_control", "mac_admin")


def _enumerate_capabilities() -> frozenset[str]:
    """Every capability name the running libcap/kernel recognises.

    ``cap_max_bits()`` returns one past the highest valid cap number
    (backed by /proc/sys/kernel/cap_last_cap). ``cap_to_name(n)`` returns
    ``"cap_<name>"`` for recognised caps and a bare decimal string for
    unknown values; we keep only the named ones, so upgrading libcap or
    the kernel automatically picks up new caps without source edits.
    """
    names = set()
    for i in range(cap_max_bits()):
        name = cap_to_name(i)
        if name.startswith("cap_"):
            names.add(name[len("cap_") :])
    return frozenset(names)


ALL_CAPABILITIES = _enumerate_capabilities()


# Each policy picks the baseline set of caps that are "off unless opted in".
# The final drop set is then ``(baseline - user-enabled) | user-disabled``:
# * DEFAULT — drop what libvirt's lxc driver drops by default
# * ALLOW   — drop nothing except what the user explicitly turned off
# * DENY    — drop everything except what the user explicitly turned on
_POLICY_BASELINES = MappingProxyType(
    {
        "DEFAULT": frozenset(DEFAULT_POLICY_DROPS),
        "ALLOW": frozenset(),
        "DENY": ALL_CAPABILITIES,
    }
)


def derive_caps(policy: str, capabilities_state: dict[str, bool]) -> tuple[list[str], list[str]]:
    """Return (drop_names, enabled_names) from the raw policy + state."""
    try:
        baseline = _POLICY_BASELINES[policy.upper()]
    except KeyError:
        raise ValueError(f"unknown capabilities policy: {policy!r}")
    enabled, disabled = set(), set()
    for n, on in capabilities_state.items():
        if on:
            enabled.add(n)
        else:
            disabled.add(n)
    return sorted((baseline - enabled) | disabled), sorted(enabled)


def build_argv_for_shell(
    uuid: str,
    uri: str,
    capabilities_policy: str,
    capabilities_state: dict[str, bool],
    has_idmap: bool,
    shell_argv: list[str],
) -> list[str]:
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
    drop_names, enabled = derive_caps(capabilities_policy, capabilities_state)
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
