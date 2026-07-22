"""Tests for enter_and_exec's fork/exec/waitpid path.

Run with user_fd=-1 and no drops/caps, so no namespace or privilege state of
the test process is touched -- only a child is forked, exec'd, and reaped.
This exercises the waitpid loop and exit-status translation.
"""
from __future__ import annotations

import signal

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


def test_benign_signal_does_not_abort_wait():
    """A signal whose Python handler returns normally must not abort the wait.

    waitpid takes the EINTR, PyErr_CheckSignals runs the handler, and the
    retry picks the child's real exit status back up. Without the retry this
    raised OSError(EINTR) and the caller lost the status entirely -- which is
    the bug the EINTR loop fixes.

    Note the handler here deliberately does *not* raise: a raising handler
    (KeyboardInterrupt) already propagated correctly before the fix, because
    the eval loop runs pending handlers while the OSError unwinds. Only the
    benign case distinguishes the two implementations.
    """
    fired = []
    old = signal.signal(signal.SIGALRM, lambda _signum, _frame: fired.append(1))
    try:
        signal.setitimer(signal.ITIMER_REAL, 0.1)
        assert enter_and_exec(-1, [], [], "", ["/bin/sh", "-c", "sleep 0.4; exit 7"]) == 7
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)
    assert fired, "SIGALRM never landed; the test did not exercise the EINTR path"
