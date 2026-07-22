"""Tests for _write_all (partial-write safety) and the -n/interactive
argument conflict."""
from __future__ import annotations

import pytest

# Importing this pulls in the compiled _native extension. If it isn't built,
# collection fails here and the run goes red -- deliberately. Build it with
# `python3 -c "from setuptools import setup; setup()" build_ext --inplace`.
from truenas_pylibvirt.nsexec import cli


def test_write_all_loops_until_drained(monkeypatch):
    written: list[bytes] = []

    def one_byte_at_a_time(fd, data):
        written.append(bytes(data[:1]))
        return 1  # short write

    monkeypatch.setattr(cli.os, "write", one_byte_at_a_time)
    cli._write_all(7, b"hello")

    assert b"".join(written) == b"hello"
    assert len(written) == 5  # every byte delivered despite short writes


# Every _die() in main() exits 2 — including the libvirt-connect failure a
# few lines below these checks, and argparse's own usage errors. So the
# argument-conflict tests must assert on the message; asserting the exit
# code alone passes even with the check deleted outright.
@pytest.mark.parametrize("extra", [["-t"], ["--mode", "interactive"]])
def test_n_conflicts_with_interactive(monkeypatch, capsys, extra):
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    with pytest.raises(SystemExit) as ei:
        cli.main(["ct", "-n", *extra])
    assert ei.value.code == 2
    assert "-n cannot be combined with interactive mode" in capsys.readouterr().err


def test_t_and_T_still_conflict(monkeypatch, capsys):
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    with pytest.raises(SystemExit) as ei:
        cli.main(["ct", "-t", "-T"])
    assert ei.value.code == 2
    assert "-t and -T are mutually exclusive" in capsys.readouterr().err
