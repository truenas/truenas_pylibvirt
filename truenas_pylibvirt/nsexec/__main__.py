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

import libvirt
import libvirt_lxc

from truenas_pylibvirt.nsexec import enter_and_exec


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

    # The only thing we need to know about each fd is whether it's the
    # user namespace, because the user-ns setns has to happen last (it
    # resets cap sets; see enter_and_exec). libvirt doesn't document the
    # order of the returned list, so identify via the ns-kind readlink
    # on /proc/self/fd/<fd> rather than a positional assumption.
    user_fd = -1
    other_fds = []
    for fd in fds:
        if os.readlink(f"/proc/self/fd/{fd}").startswith("user:"):
            user_fd = fd
        else:
            other_fds.append(fd)

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
