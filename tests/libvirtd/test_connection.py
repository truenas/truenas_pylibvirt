"""Tests for Connection's lazy, self-healing `connection` property.

The property must transparently reconnect when the cached connection is dead.
The tricky part (NAS-109072) is that a dead libvirt connection raises from the
liveness probes (isAlive()/listAllDomains()) instead of returning a falsy
value, so the probe must be caught and turned into a reconnect. Reconnects are
serialized so concurrent callers don't open (and leak) multiple connections.
"""
from __future__ import annotations

import threading
from unittest.mock import Mock

import libvirt

from truenas_pylibvirt.libvirtd.connection import Connection


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
