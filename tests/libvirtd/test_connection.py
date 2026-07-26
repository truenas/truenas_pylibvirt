"""Tests for Connection's lazy, self-healing `connection` property.

The property must transparently reconnect when the cached connection is dead.
The tricky part (NAS-109072) is that a dead libvirt connection raises from the
liveness probes (isAlive()/listAllDomains()) instead of returning a falsy
value, so the probe must be caught and turned into a reconnect. Reconnects are
serialized so concurrent callers don't open (and leak) multiple connections.

Handles that are dropped -- replaced by a reconnect, abandoned because post-open
setup failed, or closed outright -- must be deregistered as well as closed, since
a registered event callback keeps the connection alive on its own.
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


def _make_conn() -> Mock:
    conn = Mock(name="libvirt_conn")
    conn.isAlive.return_value = True
    conn.listAllDomains.return_value = []
    return conn


def test_first_access_opens_registers_and_keepalive():
    manager = Mock()
    conn = _make_conn()
    manager.open.return_value = conn

    connection = Connection(manager, "qemu:///system")
    got = connection.connection

    assert got is conn
    manager.open.assert_called_once_with("qemu:///system")
    conn.domainEventRegister.assert_called_once()
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
    conn_a.close.assert_called_once()  # dead connection dropped, not leaked
    conn_b.domainEventRegister.assert_called_once()


def test_dead_connection_reconnects_when_isalive_raises():
    manager = Mock()
    conn_a, conn_b = _make_conn(), _make_conn()
    manager.open.side_effect = [conn_a, conn_b]

    connection = Connection(manager, "uri")
    assert connection.connection is conn_a

    conn_a.isAlive.side_effect = libvirt.libvirtError("internal error")

    assert connection.connection is conn_b
    assert manager.open.call_count == 2
    conn_a.close.assert_called_once()


def test_isalive_false_reconnects():
    manager = Mock()
    conn_a, conn_b = _make_conn(), _make_conn()
    manager.open.side_effect = [conn_a, conn_b]

    connection = Connection(manager, "uri")
    assert connection.connection is conn_a

    conn_a.isAlive.return_value = False

    assert connection.connection is conn_b
    conn_a.close.assert_called_once()


def test_replaced_connection_is_deregistered_before_being_closed():
    """Closing alone doesn't release a handle that still has an event callback
    registered, so the reconnect path must deregister first."""
    manager = Mock()
    conn_a, conn_b = _make_conn(), _make_conn()
    manager.open.side_effect = [conn_a, conn_b]

    connection = Connection(manager, "uri")
    assert connection.connection is conn_a

    conn_a.isAlive.return_value = False
    assert connection.connection is conn_b

    conn_a.domainEventDeregister.assert_called_once()
    conn_a.close.assert_called_once()
    names = _call_names(conn_a)
    assert names.index("domainEventDeregister") < names.index("close")


@pytest.mark.parametrize("error", [libvirt.libvirtError("client socket is closed"), KeyError("callback")])
def test_replaced_connection_is_closed_even_when_deregistering_fails(error):
    """Deregistering a handle whose socket is already gone fails, and libvirt raises
    `KeyError` for a callback it no longer knows about. Neither may stop the close: a
    handle that is deregistered but left open is the leak this is meant to prevent."""
    manager = Mock()
    conn_a, conn_b = _make_conn(), _make_conn()
    manager.open.side_effect = [conn_a, conn_b]

    connection = Connection(manager, "uri")
    assert connection.connection is conn_a

    conn_a.domainEventDeregister.side_effect = error
    conn_a.isAlive.return_value = False

    assert connection.connection is conn_b
    conn_a.close.assert_called_once()


def test_event_register_failure_discards_handle_and_propagates():
    manager = Mock()
    conn = _make_conn()
    manager.open.return_value = conn
    conn.domainEventRegister.side_effect = libvirt.libvirtError("register failed")

    connection = Connection(manager, "uri")

    with pytest.raises(libvirt.libvirtError) as exc:
        connection.connection

    assert exc.value is conn.domainEventRegister.side_effect
    conn.domainEventDeregister.assert_called_once()
    conn.close.assert_called_once()
    assert connection._connection is None


def test_keepalive_failure_discards_handle_and_propagates():
    manager = Mock()
    conn = _make_conn()
    manager.open.return_value = conn
    conn.setKeepAlive.side_effect = libvirt.libvirtError("keepalive failed")

    connection = Connection(manager, "uri")

    with pytest.raises(libvirt.libvirtError) as exc:
        connection.connection

    assert exc.value is conn.setKeepAlive.side_effect
    conn.domainEventDeregister.assert_called_once()
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
    manager = Mock()
    conn = _make_conn()
    manager.open.return_value = conn

    connection = Connection(manager, "uri")
    assert connection.connection is conn

    connection._close()

    conn.domainEventDeregister.assert_called_once()
    conn.close.assert_called_once()
    assert connection._connection is None
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
    barrier = threading.Barrier(n)

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
    barrier = threading.Barrier(n)
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
