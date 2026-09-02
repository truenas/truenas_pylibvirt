"""Tests for Connection's lazy, self-healing `connection` property.

The property must transparently reconnect when the cached connection is dead.
The tricky part (NAS-109072) is that a dead libvirt connection raises from the
liveness probes (isAlive()/listAllDomains()) instead of returning a falsy
value, so the probe must be caught and turned into a reconnect. Reconnects are
serialized so concurrent callers don't open (and leak) multiple connections.

Handles that are dropped -- replaced by a reconnect, abandoned because post-open
setup failed, or closed outright -- must be deregistered, since a registered event
callback keeps the connection alive on its own. The handle being replaced is only
deregistered: another thread may still be inside an RPC on it, and closing would
free it underneath that thread.

The registration id of the first callback on a fresh handle is genuinely `0`, so
these mocks return `0` -- with a truthy id the suite cannot see the difference
between `if callback_id is not None` and `if callback_id`, and the latter silently
skips the deregister that the whole file exists to pin.
"""
from __future__ import annotations

import threading
from unittest.mock import Mock

import libvirt
import pytest

from truenas_pylibvirt.error import Error
from truenas_pylibvirt.libvirtd.connection import Connection


def _call_names(conn: Mock) -> list[str]:
    return [name for name, _, _ in conn.mock_calls]


def _make_conn(callback_id: int = 0) -> Mock:
    conn = Mock(name="libvirt_conn")
    conn.isAlive.return_value = True
    conn.listAllDomains.return_value = []
    conn.domainEventRegisterAny.return_value = callback_id
    return conn


def test_first_access_opens_registers_and_keepalive():
    manager = Mock()
    conn = _make_conn()
    manager.open.return_value = conn

    connection = Connection(manager, "qemu:///system")
    got = connection.connection

    assert got is conn
    manager.open.assert_called_once_with("qemu:///system")
    conn.domainEventRegisterAny.assert_called_once_with(
        None, libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE, connection._libvirt_event_callback, None
    )
    conn.setKeepAlive.assert_called_once_with(5, 3)
    conn.close.assert_not_called()  # nothing to replace on the first open


def test_alive_connection_is_reused():
    manager = Mock()
    conn = _make_conn()
    manager.open.return_value = conn

    connection = Connection(manager, "uri")

    assert connection.connection is conn
    assert connection.connection is conn
    manager.open.assert_called_once()


def test_dead_connection_reconnects_when_listalldomains_raises():
    """The regression: a dead connection whose probe RAISES must reconnect,
    not propagate the error."""
    manager = Mock()
    conn_a, conn_b = _make_conn(), _make_conn()
    manager.open.side_effect = [conn_a, conn_b]

    connection = Connection(manager, "uri")
    assert connection.connection is conn_a

    conn_a.listAllDomains.side_effect = libvirt.libvirtError("client socket is closed")

    assert connection.connection is conn_b
    assert manager.open.call_count == 2
    conn_a.domainEventDeregisterAny.assert_called_once_with(0)  # dead connection released, not leaked
    conn_b.domainEventRegisterAny.assert_called_once()


def test_dead_connection_reconnects_when_isalive_raises():
    manager = Mock()
    conn_a, conn_b = _make_conn(), _make_conn()
    manager.open.side_effect = [conn_a, conn_b]

    connection = Connection(manager, "uri")
    assert connection.connection is conn_a

    conn_a.isAlive.side_effect = libvirt.libvirtError("internal error")

    assert connection.connection is conn_b
    assert manager.open.call_count == 2
    conn_a.domainEventDeregisterAny.assert_called_once_with(0)


def test_isalive_false_reconnects():
    manager = Mock()
    conn_a, conn_b = _make_conn(), _make_conn()
    manager.open.side_effect = [conn_a, conn_b]

    connection = Connection(manager, "uri")
    assert connection.connection is conn_a

    conn_a.isAlive.return_value = False

    assert connection.connection is conn_b
    conn_a.domainEventDeregisterAny.assert_called_once_with(0)


def test_replaced_connection_is_deregistered_but_not_closed():
    """Deregistering is what releases the handle; closing it would free it under any
    thread still inside an RPC on it, since the property hands out the raw handle."""
    manager = Mock()
    conn_a, conn_b = _make_conn(), _make_conn()
    manager.open.side_effect = [conn_a, conn_b]

    connection = Connection(manager, "uri")
    assert connection.connection is conn_a

    conn_a.isAlive.return_value = False
    assert connection.connection is conn_b

    conn_a.domainEventDeregisterAny.assert_called_once_with(0)
    conn_a.close.assert_not_called()


def test_registration_id_travels_with_its_own_handle():
    """Each handle is deregistered with the id it was registered with, not with
    whatever the current handle happens to hold."""
    manager = Mock()
    conn_a, conn_b = _make_conn(callback_id=0), _make_conn(callback_id=7)
    manager.open.side_effect = [conn_a, conn_b]

    connection = Connection(manager, "uri")
    assert connection.connection is conn_a

    conn_a.isAlive.return_value = False
    assert connection.connection is conn_b

    conn_a.domainEventDeregisterAny.assert_called_once_with(0)
    connection._close()
    conn_b.domainEventDeregisterAny.assert_called_once_with(7)


@pytest.mark.parametrize("error", [libvirt.libvirtError("client socket is closed"), RuntimeError("dispatching")])
def test_reconnect_proceeds_when_deregistering_the_replaced_handle_fails(error):
    """Deregistering a handle whose socket is already gone fails. That must not abort
    the reconnect, which is the only thing that restores a working connection."""
    manager = Mock()
    conn_a, conn_b = _make_conn(), _make_conn()
    manager.open.side_effect = [conn_a, conn_b]

    connection = Connection(manager, "uri")
    assert connection.connection is conn_a

    conn_a.domainEventDeregisterAny.side_effect = error
    conn_a.isAlive.return_value = False

    assert connection.connection is conn_b


def test_failed_reopen_leaves_no_handle_installed():
    """A reconnect that cannot open must not leave the discarded handle installed,
    or the next access would probe a handle that has already been given back."""
    manager = Mock()
    conn_a = _make_conn()
    manager.open.side_effect = [conn_a, libvirt.libvirtError("connect failed")]

    connection = Connection(manager, "uri")
    assert connection.connection is conn_a

    conn_a.isAlive.return_value = False

    with pytest.raises(libvirt.libvirtError):
        connection.connection

    assert connection._connection is None
    assert connection._callback_id is None


def test_event_register_failure_discards_handle_and_propagates():
    manager = Mock()
    conn = _make_conn()
    manager.open.return_value = conn
    conn.domainEventRegisterAny.side_effect = libvirt.libvirtError("register failed")

    connection = Connection(manager, "uri")

    with pytest.raises(libvirt.libvirtError) as exc:
        connection.connection

    assert exc.value is conn.domainEventRegisterAny.side_effect
    # Registration never completed, so there is no id to give back -- only the handle.
    conn.domainEventDeregisterAny.assert_not_called()
    conn.close.assert_called_once()
    assert connection._connection is None


def test_keepalive_failure_discards_handle_and_propagates():
    """Registration succeeded before keepalive failed, so this handle is pinned by its
    callback and has to be deregistered as well as closed."""
    manager = Mock()
    conn = _make_conn()
    manager.open.return_value = conn
    conn.setKeepAlive.side_effect = libvirt.libvirtError("keepalive failed")

    connection = Connection(manager, "uri")

    with pytest.raises(libvirt.libvirtError) as exc:
        connection.connection

    assert exc.value is conn.setKeepAlive.side_effect
    conn.domainEventDeregisterAny.assert_called_once_with(0)
    conn.close.assert_called_once()
    names = _call_names(conn)
    assert names.index("domainEventDeregisterAny") < names.index("close")
    assert connection._connection is None


def test_setup_failure_discards_the_handle_whatever_the_error_type():
    """Registration pins the handle the moment it succeeds, so whether the handle has to
    be given back depends on setup not having finished -- not on which exception says so."""
    manager = Mock()
    conn = _make_conn()
    manager.open.return_value = conn
    conn.setKeepAlive.side_effect = RuntimeError("binding changed under us")

    connection = Connection(manager, "uri")

    with pytest.raises(RuntimeError):
        connection.connection

    conn.domainEventDeregisterAny.assert_called_once_with(0)
    conn.close.assert_called_once()
    assert connection._connection is None


def test_setup_failure_propagates_original_error_when_discard_fails():
    """A failure while cleaning up must not mask the error that caused it."""
    manager = Mock()
    conn = _make_conn()
    manager.open.return_value = conn
    conn.setKeepAlive.side_effect = libvirt.libvirtError("keepalive failed")
    conn.close.side_effect = libvirt.libvirtError("close failed")

    connection = Connection(manager, "uri")

    with pytest.raises(libvirt.libvirtError) as exc:
        connection.connection

    assert exc.value is conn.setKeepAlive.side_effect


def test_close_of_unopened_connection_does_not_open_one():
    manager = Mock()

    connection = Connection(manager, "uri")
    connection._close()

    manager.open.assert_not_called()


def test_close_deregisters_and_clears_the_handle():
    """Explicit teardown has no other user to trip over, so it closes as well as
    deregisters and the handle is gone by the time it returns."""
    manager = Mock()
    conn = _make_conn()
    manager.open.return_value = conn

    connection = Connection(manager, "uri")
    assert connection.connection is conn

    connection._close()

    conn.domainEventDeregisterAny.assert_called_once_with(0)
    conn.close.assert_called_once()
    names = _call_names(conn)
    assert names.index("domainEventDeregisterAny") < names.index("close")
    assert connection._connection is None
    assert connection._callback_id is None
    manager.open.assert_called_once()  # never reopened just to be closed


def test_close_reports_a_handle_it_could_not_close():
    manager = Mock()
    conn = _make_conn()
    manager.open.return_value = conn
    conn.close.side_effect = libvirt.libvirtError("close failed")

    connection = Connection(manager, "uri")
    assert connection.connection is conn

    with pytest.raises(Error):
        connection._close()

    # The handle is unusable once close() has failed, so it must not stay installed.
    assert connection._connection is None


def test_concurrent_close_closes_once():
    """Only the caller that claims the handle closes it; the rest see it already gone.

    This exercises contention rather than proving the swap is atomic -- under the GIL a
    thread switch between reading and clearing `_connection` is not reachable from a test.
    """
    manager = Mock()
    conn = _make_conn()
    manager.open.return_value = conn

    connection = Connection(manager, "uri")
    assert connection.connection is conn

    n = 8
    barrier = threading.Barrier(n, timeout=30)

    def worker() -> None:
        barrier.wait()
        connection._close()

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    conn.close.assert_called_once()


def test_concurrent_access_opens_once():
    """Under contention the reconnect is serialized: exactly one open, and
    every caller gets the same connection object."""
    manager = Mock()
    # Distinct object per open() so a double-open would be observable.
    manager.open.side_effect = [_make_conn() for _ in range(16)]

    connection = Connection(manager, "uri")

    n = 8
    barrier = threading.Barrier(n, timeout=30)
    results: list = []
    results_lock = threading.Lock()

    def worker() -> None:
        barrier.wait()  # maximize contention on the first access
        conn = connection.connection
        with results_lock:
            results.append(conn)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    manager.open.assert_called_once()
    assert len(results) == n
    assert all(r is results[0] for r in results)
