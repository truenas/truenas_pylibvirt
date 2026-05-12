"""``truenas-nsexec`` — CLI for running a command in a libvirt container.

Resolves the container by name or UUID, reads the capability policy
and idmap presence from the live domain XML, sanitises the environment,
and enters the container via :func:`._runner.run_in_container`. A PTY
is allocated when stdin and stdout are both TTYs; ``-t`` / ``-T``
override the autodetection.

Limitations (see the package docstring):

* No LSM (AppArmor/SELinux) re-entry — the exec'd shell runs under the
  host's security label, not the container's.
* No ``--user`` / ``--group`` / ``--cwd`` — the C primitive hardcodes
  ``setresuid(0)`` / ``setresgid(0)`` in the post-fork child and has no
  chdir hook.

Flags must be passed before the positional target. Anything after the
target (and any ``--``) becomes the in-container command.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import os
import pty
import select
import signal
import struct
import sys
import termios
import tty
import uuid as _uuid
from xml.etree import ElementTree

import libvirt

# NOTE: do NOT import ``derive_caps`` (from package ``__init__``) or
# ``run_in_container`` (from ``_runner``) at module top — both pull in
# the compiled ``_native`` extension. ``argparse-manpage`` loads this
# file during the Debian build via ``--pyfile`` (runpy), and at that
# point the C extension is staged under ``.pybuild/`` and not on
# ``sys.path``. Deferring those imports into the functions that
# actually need them keeps :func:`get_parser` introspectable without
# building the extension first.


LIBVIRT_URI = "lxc:///system?socket=/run/truenas_libvirt/libvirt-sock"
DEFAULT_COMMAND = ["/bin/sh"]
DEFAULT_HOME = "/root"
DEFAULT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def _die(message: str, code: int = 2) -> None:
    sys.stderr.write(f"truenas-nsexec: {message}\n")
    sys.exit(code)


def _silence_libvirt_errors() -> None:
    """Suppress libvirt's default stderr error logging.

    Without this, intermediate failed lookups in :func:`_resolve_domain`
    (e.g. ``lookupByName`` on a friendly name, which never matches
    because the library stores the UUID in ``<name>``) leak a line like
    ``libvirt: LXC Driver error : Domain not found: ...`` to the user's
    terminal before the Python ``libvirtError`` is even raised and
    handled. Mirrors the no-op handler installed by the in-process
    ``ConnectionManager`` so this CLI behaves consistently with the
    middleware path. Real failure messaging is emitted via :func:`_die`.
    """
    libvirt.registerErrorHandler(lambda _ctx, _err: None, None)


def _looks_like_uuid(s: str) -> bool:
    try:
        _uuid.UUID(s)
    except ValueError:
        return False
    return True


def _resolve_by_title(conn: libvirt.virConnect, target: str) -> libvirt.virDomain | None:
    """Find a running domain whose ``<title>`` matches ``target``.

    The library generates domain XML with ``<name>`` set to the UUID and
    the user-facing name in ``<title>`` (see ``domain/base/xml.py``), so
    libvirt's ``lookupByName`` never matches the friendly name a user
    types. Iterating active domains and matching ``<title>`` is the only
    way to honour that input form.
    """
    flags = libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE
    for dom in conn.listAllDomains(flags):
        try:
            xml = dom.XMLDesc()
        except libvirt.libvirtError:
            continue
        if ElementTree.fromstring(xml).findtext("title") == target:
            return dom
    return None


def _resolve_domain(conn: libvirt.virConnect, target: str) -> libvirt.virDomain:
    """Look up the target by UUID, libvirt name, or friendly ``<title>``."""
    if _looks_like_uuid(target):
        try:
            return conn.lookupByUUIDString(target)
        except libvirt.libvirtError as e:
            _die(f"no domain with UUID {target!r}: {e}")
    try:
        return conn.lookupByName(target)
    except libvirt.libvirtError:
        pass
    if dom := _resolve_by_title(conn, target):
        return dom
    _die(f"no domain named or titled {target!r}")


def _parse_caps_and_idmap(xml: str) -> tuple[list[str], str, bool]:
    """Extract (drop_names, caps_text, has_idmap) from live ``XMLDesc()``.

    ``drop_names`` are full libcap names (``cap_<short>``), matching the
    format :func:`enter_and_exec` expects. ``caps_text`` is the libcap
    text spec for the explicit effective+permitted set (empty when no
    caps are enabled by the policy).
    """
    from . import derive_caps

    root = ElementTree.fromstring(xml)
    caps_el = root.find("./features/capabilities")
    if caps_el is not None:
        policy = caps_el.get("policy", "default")
        state = {
            child.tag: child.get("state") == "on"
            for child in caps_el
            if child.get("state") in ("on", "off")
        }
    else:
        policy = "default"
        state = {}
    short_drops, enabled = derive_caps(policy, state)
    drop_names = [f"cap_{n}" for n in short_drops]
    caps_text = f"{','.join('cap_' + n for n in enabled)}+ep" if enabled else ""
    has_idmap = root.find("./idmap") is not None
    return drop_names, caps_text, has_idmap


def _parse_env_overrides(items: list[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            _die(f"--env value {item!r} missing '='")
        k, _, v = item.partition("=")
        env[k] = v
    return env


def _build_environment(overrides: dict[str, str]) -> dict[str, str]:
    """Sanitised default env layered with user overrides.

    A small fixed default set (TERM/HOME/PATH/LC_ALL) plus user
    ``--env`` overrides, rather than inheriting the host's full
    environment — keeps the in-container shell from picking up
    arbitrary host configuration.
    """
    env = {
        "TERM": os.environ.get("TERM", "xterm"),
        "HOME": DEFAULT_HOME,
        "PATH": DEFAULT_PATH,
        "LC_ALL": "C.UTF-8",
    }
    env.update(overrides)
    return env


def _get_winsize(fd: int) -> bytes:
    try:
        return fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8)
    except OSError:
        return struct.pack("HHHH", 24, 80, 0, 0)


def _decide_interactive(args: argparse.Namespace) -> bool:
    if args.disable_stdin:
        return False
    if args.force_interactive:
        return True
    if args.force_non_interactive:
        return False
    if args.mode == "interactive":
        return True
    if args.mode == "non-interactive":
        return False
    return os.isatty(0) and os.isatty(1)


def _relay(stdin_fd: int, master_fd: int) -> None:
    """Ferry bytes between host stdin/stdout and the PTY master.

    No decoding — raw bytes pass straight through; the host terminal
    owns encoding. Stops when the master returns EIO (slave closed by
    the last in-container process) or EOF.
    """
    read_fds = [stdin_fd, master_fd]
    while True:
        try:
            ready, _, _ = select.select(read_fds, [], [])
        except OSError as e:
            if e.errno == errno.EINTR:
                continue
            raise
        if master_fd in ready:
            try:
                data = os.read(master_fd, 4096)
            except OSError as e:
                if e.errno == errno.EIO:
                    return
                raise
            if not data:
                return
            os.write(1, data)
        if stdin_fd in ready:
            try:
                data = os.read(stdin_fd, 4096)
            except OSError:
                # stdin failed — stop polling it but keep relaying output
                read_fds = [master_fd]
                continue
            if not data:
                # Host stdin closed (e.g., piped input ran out). Don't
                # break the loop — the in-container process may still
                # be producing output we need to forward.
                read_fds = [master_fd]
                continue
            os.write(master_fd, data)


def _run_interactive(
    dom: libvirt.virDomain,
    drop_names: list[str],
    caps_text: str,
    has_idmap: bool,
    argv: list[str],
) -> int:
    from ._runner import run_in_container

    master, slave = pty.openpty()
    initial_winsize = _get_winsize(1)

    pid = os.fork()
    if pid == 0:
        # Reset inherited signal dispositions. Defensive: a Python
        # handler installed in the parent would queue a flag the
        # interpreter checks between bytecodes; if the handler ran
        # during run_in_container's Python sections it could touch fds
        # the child has already closed.
        for sig in (
            signal.SIGWINCH,
            signal.SIGINT,
            signal.SIGTERM,
            signal.SIGTSTP,
            signal.SIGTTIN,
            signal.SIGTTOU,
        ):
            signal.signal(sig, signal.SIG_DFL)

        try:
            # Isolate from the host terminal's foreground process group
            # so e.g. Ctrl-C at the host shell hits the relay parent only.
            # Claiming the slave PTY as our controlling terminal is left
            # to the post-fork child inside the container's PID namespace
            # (see py_enter_and_exec) so the foreground pgid recorded on
            # the tty is a pid that's visible to the in-container shell.
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, initial_winsize)
            os.dup2(slave, 0)
            os.dup2(slave, 1)
            os.dup2(slave, 2)
            os.close(master)
            os.close(slave)
            status = run_in_container(dom, drop_names, caps_text, has_idmap, argv)
        except Exception as e:
            # After dup2, fd 2 is the PTY slave — the message reaches
            # the parent's relay and lands on the user's terminal.
            os.write(2, f"truenas-nsexec child: {e}\r\n".encode())
            os._exit(1)
        os._exit(status)

    os.close(slave)

    saved_termios = None
    saved_winch = None
    try:
        if os.isatty(0):
            saved_termios = termios.tcgetattr(0)
            tty.setraw(0)

        def _winch_handler(_signo: int, _frame: object) -> None:
            try:
                size = fcntl.ioctl(1, termios.TIOCGWINSZ, b"\0" * 8)
                fcntl.ioctl(master, termios.TIOCSWINSZ, size)
            except OSError:
                pass

        saved_winch = signal.signal(signal.SIGWINCH, _winch_handler)

        _relay(0, master)

        _, status = os.waitpid(pid, 0)
    finally:
        if saved_winch is not None:
            signal.signal(signal.SIGWINCH, saved_winch)
        if saved_termios is not None:
            with contextlib.suppress(termios.error):
                termios.tcsetattr(0, termios.TCSADRAIN, saved_termios)
        with contextlib.suppress(OSError):
            os.close(master)

    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return 1


def _run_non_interactive(
    dom: libvirt.virDomain,
    drop_names: list[str],
    caps_text: str,
    has_idmap: bool,
    argv: list[str],
    disable_stdin: bool,
) -> int:
    from ._runner import run_in_container

    if disable_stdin:
        fd = os.open(os.devnull, os.O_RDONLY)
        os.dup2(fd, 0)
        os.close(fd)
    return run_in_container(dom, drop_names, caps_text, has_idmap, argv)


def get_parser() -> argparse.ArgumentParser:
    """Construct the argument parser for ``truenas-nsexec``.

    Exposed as a module-level function (rather than built inline in
    :func:`main`) so ``argparse-manpage`` can introspect it during the
    Debian build to generate the man page. Keep this function free of
    side effects and free of imports that pull in the ``_native`` C
    extension — see the note at the top of the module.
    """
    p = argparse.ArgumentParser(
        prog="truenas-nsexec",
        description=(
            "Run a command inside a running libvirt container. Resolves the "
            "container by name or UUID, reads its capability policy and "
            "idmap configuration from libvirt, enters the container's "
            "namespaces, and execs the given command. If no command is "
            "given, /bin/sh is started. A pseudo-terminal is allocated when "
            "stdin and stdout are both TTYs (see --mode, -t, -T). "
            "This tool is experimental; see the Stability section below."
        ),
        epilog=(
            "Examples:\n"
            "  truenas-nsexec mycontainer\n"
            "      Open an interactive shell in 'mycontainer'.\n"
            "\n"
            "  truenas-nsexec mycontainer -- ls -lh /var/log\n"
            "      Run 'ls -lh /var/log' inside the container.\n"
            "\n"
            "  echo hello | truenas-nsexec mycontainer -- cat\n"
            "      Pipe input to a non-interactive command.\n"
            "\n"
            "  truenas-nsexec --env LANG=fr_FR.UTF-8 mycontainer -- locale\n"
            "      Set an environment variable for the in-container command.\n"
            "\n"
            "  truenas-nsexec 5f3a4b6c-1234-5678-9abc-def012345678 -- hostname\n"
            "      Look up the container by UUID.\n"
            "\n"
            "Notes:\n"
            "  Flags must precede the positional <target>. Anything after the\n"
            "  target (and an optional '--') is treated as the command to run\n"
            "  inside the container.\n"
            "\n"
            "Exit status:\n"
            "  Mirrors the in-container process: its own exit code on normal\n"
            "  exit, or 128 + signal number if it was terminated by a signal.\n"
            "  Argument errors and unreachable containers exit with status 2.\n"
            "\n"
            "Stability:\n"
            "  This tool is experimental. Its command-line surface, output\n"
            "  format, and behavior may change between TrueNAS versions\n"
            "  without notice. It is provided as a convenience and ships with\n"
            "  no guarantees of stability, security, or fitness for use.\n"
            "\n"
            "See also:\n"
            "  virsh(1)\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "target",
        metavar="TARGET",
        help=(
            "Container to enter, identified by name or UUID. If the value "
            "parses as a UUID it is looked up that way; otherwise it is "
            "treated as a container name. The container must be running."
        ),
    )
    p.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="KEY=VAL",
        help=(
            "Set an environment variable for the in-container command. May "
            "be repeated. Layered on top of a sanitized default set "
            "(TERM, HOME=/root, PATH=" + DEFAULT_PATH + ", LC_ALL=C.UTF-8); "
            "your override wins on conflict. The host's wider environment "
            "is NOT inherited."
        ),
    )
    p.add_argument(
        "--mode",
        choices=("auto", "interactive", "non-interactive"),
        default="auto",
        metavar="MODE",
        help=(
            "How stdio is wired to the in-container process. 'auto' (the "
            "default) allocates a pseudo-terminal only when stdin and "
            "stdout are both TTYs. 'interactive' always allocates a PTY. "
            "'non-interactive' never does and forwards stdio directly."
        ),
    )
    p.add_argument(
        "-t",
        dest="force_interactive",
        action="store_true",
        help=(
            "Force pseudo-terminal allocation regardless of whether stdin "
            "and stdout are TTYs. Equivalent to '--mode interactive'. "
            "Mutually exclusive with -T and --mode."
        ),
    )
    p.add_argument(
        "-T",
        dest="force_non_interactive",
        action="store_true",
        help=(
            "Disable pseudo-terminal allocation regardless of stdio. "
            "Equivalent to '--mode non-interactive'. Mutually exclusive "
            "with -t and --mode."
        ),
    )
    p.add_argument(
        "-n",
        dest="disable_stdin",
        action="store_true",
        help=(
            "Redirect stdin from /dev/null inside the container. Use for "
            "non-interactive invocations that should not consume the "
            "caller's stdin (e.g. when running from a script)."
        ),
    )
    p.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        metavar="COMMAND",
        help=(
            "Command and arguments to execute inside the container. Pass "
            "'--' before the command if it starts with a flag (e.g. "
            "'truenas-nsexec ct -- ls -lh /'). If omitted, defaults to "
            f"{' '.join(DEFAULT_COMMAND)}."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> None:
    args = get_parser().parse_args(argv)

    if args.force_interactive and args.force_non_interactive:
        _die("-t and -T are mutually exclusive")
    if args.mode != "auto" and (args.force_interactive or args.force_non_interactive):
        _die("--mode is mutually exclusive with -t/-T")

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        command = list(DEFAULT_COMMAND)

    _silence_libvirt_errors()
    try:
        conn = libvirt.open(LIBVIRT_URI)
    except libvirt.libvirtError as e:
        _die(f"cannot connect to {LIBVIRT_URI}: {e}")

    dom = _resolve_domain(conn, args.target)

    if dom.OSType() != "exe":
        _die(
            f"domain {args.target!r} is not a libvirt container "
            f"(OS type {dom.OSType()!r})"
        )
    if not dom.isActive():
        _die(f"domain {args.target!r} is not running")

    drop_names, caps_text, has_idmap = _parse_caps_and_idmap(dom.XMLDesc())

    env = _build_environment(_parse_env_overrides(args.env))
    os.environ.clear()
    os.environ.update(env)

    interactive = _decide_interactive(args)

    if interactive:
        status = _run_interactive(dom, drop_names, caps_text, has_idmap, command)
    else:
        status = _run_non_interactive(
            dom, drop_names, caps_text, has_idmap, command, args.disable_stdin
        )
    sys.exit(status)


if __name__ == "__main__":
    main()
