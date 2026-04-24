"""CLI entry point used by middleware's webshell to open a shell inside a
container. Invoked as:

    python3 -m truenas_pylibvirt.nsexec <uri> <uuid> <drop_csv> <caps_text> <with_user 0|1> <argv...>

Connects to libvirt at <uri>, looks up the container by <uuid>, gets its
namespace fds via virDomainLxcOpenNamespace, and hands them to the C
helper :func:`enter_and_exec`. Using libvirt for fd acquisition avoids the
PID-reuse race that ``open("/proc/<pid>/ns/*")`` has if the container's
init exits between the PID lookup and the setns sequence.
"""

import os
import sys
from types import MappingProxyType

import libvirt
import libvirt_lxc

from truenas_pylibvirt.nsexec import (
    CLONE_NEWIPC,
    CLONE_NEWNET,
    CLONE_NEWNS,
    CLONE_NEWPID,
    CLONE_NEWUSER,
    CLONE_NEWUTS,
    enter_and_exec,
)


# Maps the short names that appear in /proc/self/fd/<fd> readlinks
# ("user:[...]", "mnt:[...]", ...) to the CLONE_NEW* flag required by setns.
_NS_KIND_TO_FLAG = MappingProxyType(
    {
        "user": CLONE_NEWUSER,
        "mnt": CLONE_NEWNS,
        "uts": CLONE_NEWUTS,
        "ipc": CLONE_NEWIPC,
        "net": CLONE_NEWNET,
        "pid": CLONE_NEWPID,
    }
)


def _classify_ns_fds(fds):
    """Read /proc/self/fd/<fd> symlinks to identify each namespace fd by
    kind. libvirt's Python binding documents that the returned fds are for
    setns(2) but doesn't promise a specific ordering across versions;
    mapping by symlink target is cheap and future-proof.

    Returns ``(user_fd, other_fds)`` where ``user_fd`` is an int (or -1 if
    no user namespace was returned) and ``other_fds`` is a list of
    ``(fd, nstype_flag)`` tuples in the order libvirt returned them
    (user-ns excluded).
    """
    user_fd = -1
    other = []
    for fd in fds:
        target = os.readlink(f"/proc/self/fd/{fd}")
        kind = target.split(":", 1)[0]
        flag = _NS_KIND_TO_FLAG.get(kind)
        if flag is None:
            # Unknown namespace kind — close to avoid leaking and skip.
            os.close(fd)
            continue
        if flag == CLONE_NEWUSER:
            user_fd = fd
        else:
            other.append((fd, flag))
    return user_fd, other


def main() -> None:
    uri = sys.argv[1]
    uuid = sys.argv[2]
    drop_csv = sys.argv[3]
    caps_text = sys.argv[4]
    with_user = sys.argv[5] == "1"
    argv = sys.argv[6:]

    conn = libvirt.open(uri)
    dom = conn.lookupByUUIDString(uuid)
    fds = libvirt_lxc.lxcOpenNamespace(dom, 0)

    user_fd, other_fds = _classify_ns_fds(fds)

    # If the container has no idmap configured the caller passes
    # with_user=0; in that case skip entering the user namespace so the
    # process keeps host credentials.
    if not with_user and user_fd >= 0:
        os.close(user_fd)
        user_fd = -1

    drop_names = [n for n in drop_csv.split(",") if n]
    status = enter_and_exec(user_fd, other_fds, drop_names, caps_text, argv)
    sys.exit(status)


if __name__ == "__main__":
    main()
