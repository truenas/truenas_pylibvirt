"""Tests for enter_and_exec's fork/exec/waitpid path.

Run with user_fd=-1 and no drops/caps, so no namespace or privilege state of
the test process is touched -- only a child is forked, exec'd, and reaped.
This exercises the waitpid loop and exit-status translation.
"""
from __future__ import annotations

import contextlib
import os
import signal
import time

import pytest

from truenas_pylibvirt.nsexec._native import enter_and_exec


def test_exit_zero():
    assert enter_and_exec(-1, [], [], "", ["/bin/true"]) == 0


def test_exit_nonzero():
    assert enter_and_exec(-1, [], [], "", ["/bin/false"]) == 1


def test_command_not_found():
    assert enter_and_exec(-1, [], [], "", ["/nonexistent-command-xyz"]) == 127


def test_terminated_by_signal():
    # Child SIGKILLs itself -> 128 + 9.
    assert enter_and_exec(-1, [], [], "", ["/bin/sh", "-c", "kill -9 $$"]) == 137


def test_empty_argv_rejected():
    with pytest.raises(ValueError, match="argv must not be empty"):
        enter_and_exec(-1, [], [], "", [])


def test_pending_signal_interrupts_wait():
    """A Python signal handler firing while enter_and_exec is blocked in
    waitpid must run and its exception propagate *promptly*, not be swallowed
    by the EINTR retry until the child exits on its own. The child runs for 1s;
    the alarm fires at 0.1s, so a correct wait returns well under 0.5s while a
    blind retry only returns after the full sleep."""
    def _boom(_signum, _frame):
        raise KeyboardInterrupt

    old = signal.signal(signal.SIGALRM, _boom)
    try:
        signal.setitimer(signal.ITIMER_REAL, 0.1)
        start = time.monotonic()
        with pytest.raises(KeyboardInterrupt):
            enter_and_exec(-1, [], [], "", ["/bin/sh", "-c", "sleep 1"])
        elapsed = time.monotonic() - start
        assert elapsed < 0.5, f"wait was not interrupted promptly ({elapsed:.2f}s)"
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)
        # Reap the in-container child the interrupted wait left running.
        with contextlib.suppress(ChildProcessError):
            os.waitpid(-1, 0)
