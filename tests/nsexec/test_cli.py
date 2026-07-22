"""Tests for _write_all (partial-write safety) and the -n/interactive
argument conflict."""
from __future__ import annotations

import pytest

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


def test_write_all_single_shot(monkeypatch):
    calls: list[bytes] = []

    def full_write(fd, data):
        calls.append(bytes(data))
        return len(data)

    monkeypatch.setattr(cli.os, "write", full_write)
    cli._write_all(7, b"hi")

    assert calls == [b"hi"]


@pytest.mark.parametrize("extra", [["-t"], ["--mode", "interactive"]])
def test_n_conflicts_with_interactive(monkeypatch, extra):
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    with pytest.raises(SystemExit) as ei:
        cli.main(["ct", "-n", *extra])
    assert ei.value.code == 2


def test_t_and_T_still_conflict(monkeypatch):
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    with pytest.raises(SystemExit) as ei:
        cli.main(["ct", "-t", "-T"])
    assert ei.value.code == 2
