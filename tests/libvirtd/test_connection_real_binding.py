"""Tests for Connection against a real libvirt handle rather than a mock.

The mocked tests can only pin that we call the binding a particular way; they cannot
see whether the call actually gives the handle back. libvirt's built-in `test` driver
needs no daemon and delivers real lifecycle events, so it can answer both questions:
`close()` returns 0 only once the connection is really disposed, which is exactly the
signal that the event registration has been released.

Each `test:///default` connection is its own private instance, so a handle only ever
sees events for domains defined through it.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import libvirt
import pytest

from truenas_pylibvirt.libvirtd.connection import Connection

URI = "test:///default"

DOMAIN_XML = """
<domain type='test'>
  <name>{name}</name>
  <memory unit='KiB'>8192</memory>
  <os><type arch='i686'>hvm</type></os>
</domain>
"""


class _Handle:
    """A real libvirt handle that also answers `setKeepAlive`, can be told to report
    itself dead, and remembers what `close()` returned.

    The test driver does not implement keepalive, so a bare handle would always send
    `Connection` down its setup-failure path. `close()`'s return value is the useful
    part: 0 means libvirt disposed the connection, 1 means something still holds a
    reference to it -- an event callback that was never given back, for instance.
    """

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self.close_rc: int | None = None
        self.report_dead = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    def isAlive(self) -> bool:
        if self.report_dead:
            return False

        return bool(self._connection.isAlive())

    def setKeepAlive(self, interval: int, count: int) -> int:
        return 0

    def close(self) -> int:
        self.close_rc = self._connection.close()
        return self.close_rc


class _Manager:
    def open(self, uri: str) -> _Handle:
        return _Handle(libvirt.open(uri))


@pytest.fixture(scope="module", autouse=True)
def libvirt_event_loop():
    """Registering an event callback needs an event implementation, and something has
    to run it for callbacks to ever be dispatched."""
    libvirt.virEventRegisterDefaultImpl()

    stop = threading.Event()

    def run() -> None:
        while not stop.is_set():
            libvirt.virEventRunDefaultImpl()

    thread = threading.Thread(target=run, name="test_libvirt_event_loop", daemon=True)
    thread.start()
    yield
    stop.set()


def _wait_for(events: list, count: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(events) >= count:
            return

        time.sleep(0.01)

    raise AssertionError(f"expected {count} domain events, got {len(events)}: {events}")


def test_closing_a_deregistered_handle_disposes_it():
    """The mutation this exists to catch -- deregistering with the wrong id, or a
    callback we never registered -- leaves the handle pinned, and `close()` says so."""
    connection = Connection(_Manager(), URI)
    handle = connection.connection

    connection._close()

    assert handle.close_rc == 0


def test_lifecycle_events_reach_registered_callbacks():
    connection = Connection(_Manager(), URI)
    events: list = []
    connection.register_domain_event_callback(events.append)

    try:
        handle = connection.connection
        domain = handle.defineXML(DOMAIN_XML.format(name="pylibvirt-events"))
        _wait_for(events, 1)
        # Both events have to arrive before the close: closing gives the registration
        # back, and nothing delivers events to a handle that no longer holds one.
        domain.undefine()
        _wait_for(events, 2)
    finally:
        connection._close()

    assert [e.event.value for e in events[:2]] == ["DEFINED", "UNDEFINED"]
    assert {e.uuid for e in events[:2]} == {"pylibvirt-events"}


def test_reconnecting_from_inside_event_dispatch_is_clean(capfd):
    """The callback runs on the event loop while libvirt is walking its callbacks, so a
    reconnect from there gives the registration back mid-dispatch. Anything raised there
    escapes into libvirt's C trampoline, which prints it straight to fd 2 -- past
    logging, and past anything a debug bundle collects.

    The reconnect has to go through the liveness probe rather than clearing
    `_connection` directly, or `_open` has nothing to discard and the reentrancy this
    is about never happens.
    """
    connection = Connection(_Manager(), URI)
    events: list = []
    triggered = threading.Event()
    reconnected = threading.Event()

    handle = connection.connection

    def callback(event) -> None:
        events.append(event)
        if not triggered.is_set():
            triggered.set()
            handle.report_dead = True
            try:
                connection.connection
            finally:
                reconnected.set()

    connection.register_domain_event_callback(callback)

    try:
        handle.defineXML(DOMAIN_XML.format(name="pylibvirt-reentrant"))
        _wait_for(events, 1)
        assert reconnected.wait(10), "the reconnect never ran inside the dispatch callback"

        # The handle really was replaced, and the replacement really is registered:
        # driving an event through it proves dispatch survived the deregistration.
        new_handle = connection.connection
        assert new_handle is not handle
        new_handle.defineXML(DOMAIN_XML.format(name="pylibvirt-reentrant-2"))
        _wait_for(events, 2)
    finally:
        connection._close()

    assert "RuntimeError" not in capfd.readouterr().err
