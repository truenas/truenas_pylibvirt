"""Tests for the __main__ wire entry point's argument validation (fail-closed
on a malformed idmap flag rather than defaulting to privileged)."""
from __future__ import annotations

from unittest.mock import Mock

import pytest

import truenas_pylibvirt.nsexec.__main__ as entry


def test_too_few_args_exits(monkeypatch):
    monkeypatch.setattr(entry.sys, "argv", ["prog", "uri", "uuid", "drops"])
    with pytest.raises(SystemExit, match="usage"):
        entry.main()


def test_bad_idmap_flag_exits(monkeypatch):
    # 5-element wire; the idmap flag (position 4) is "yes", which is neither
    # "0" nor "1". libvirt.open is left unmocked on purpose: if the validation
    # were dropped, "yes" -> has_idmap=False and main() would fall through to a
    # real libvirt.open() error instead of this SystemExit, failing the test.
    monkeypatch.setattr(entry.sys, "argv", ["prog", "uri", "uuid", "drops", "yes"])
    with pytest.raises(SystemExit, match="idmap flag"):
        entry.main()


def test_valid_args_forward_to_runner(monkeypatch):
    monkeypatch.setattr(
        entry.sys, "argv",
        ["prog", "uri", "uu", "cap_a,cap_b", "1", "/bin/sh", "-c", "id"],
    )
    dom = Mock()
    conn = Mock()
    conn.lookupByUUIDString.return_value = dom
    monkeypatch.setattr(entry.libvirt, "open", Mock(return_value=conn))
    run = Mock(return_value=0)
    monkeypatch.setattr(entry, "run_in_container", run)

    with pytest.raises(SystemExit) as ei:
        entry.main()

    assert ei.value.code == 0
    run.assert_called_once_with(dom, ["cap_a", "cap_b"], True, ["/bin/sh", "-c", "id"])
