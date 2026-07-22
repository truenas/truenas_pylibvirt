"""CLI entry point used by middleware's webshell to open a shell inside a
container. Invoked as:

    python3 -m truenas_pylibvirt.nsexec <uri> <uuid> <drop_csv> <caps_text> <with_user 0|1> <argv...>

The argv shape is produced by :func:`build_argv_for_shell` and consumed
by webshell_app.py. Keep it stable. The user-facing CLI (``truenas-nsexec``,
implemented in :mod:`cli`) shares the same in-process runner —
:func:`._runner.run_in_container` — but resolves caps and idmap from the
live domain XML instead of from positional args.
"""

import sys

import libvirt

from ._runner import run_in_container


def main() -> None:
    if len(sys.argv) < 6:
        raise SystemExit(
            "usage: python3 -m truenas_pylibvirt.nsexec "
            "<uri> <uuid> <drop_csv> <caps_text> <0|1> [argv...]"
        )
    uri, uuid, drop_csv, caps_text, idmap_flag = sys.argv[1:6]
    if idmap_flag not in ("0", "1"):
        raise SystemExit(f"idmap flag must be '0' or '1', got {idmap_flag!r}")
    has_idmap = idmap_flag == "1"
    argv = sys.argv[6:]

    conn = libvirt.open(uri)
    dom = conn.lookupByUUIDString(uuid)

    drop_names = [n for n in drop_csv.split(",") if n]
    status = run_in_container(dom, drop_names, caps_text, has_idmap, argv)
    sys.exit(status)


if __name__ == "__main__":
    main()
