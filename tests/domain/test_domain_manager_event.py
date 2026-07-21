"""Regression tests for DomainManager._domain_event_callback().

A stop event is delivered asynchronously by the libvirt event thread. On a
restart (destroy + immediate start) it can arrive after start() has already
re-created and re-tracked the domain, so the callback must re-check the live
state and refuse to tear down a domain that is running now. It must still clean
up when the domain is genuinely stopped or has been undefined (get_domain() ->
None).
"""
from __future__ import annotations

from unittest.mock import Mock

import libvirt
import pytest

import truenas_pylibvirt.domain.manager as manager_mod
from truenas_pylibvirt.domain.manager import DomainManager
from truenas_pylibvirt.libvirtd.connection import DomainEvent, DomainState, VirDomainEvent


def _libvirt_error(code: int) -> libvirt.libvirtError:
    e = libvirt.libvirtError("error")
    e.err = (code, None, "message", None, None, None, None, -1, -1)
    return e


@pytest.fixture
def runtime_cleanup(monkeypatch):
    cleanup = Mock()
    monkeypatch.setattr(manager_mod.runtime, "cleanup_for_uuid", cleanup)
    return cleanup


def _event(uuid: str = "uuid-1", event: VirDomainEvent = VirDomainEvent.STOPPED) -> DomainEvent:
    return DomainEvent(event=event, uuid=uuid)


def test_stale_stop_event_does_not_tear_down_running_domain(mock_connection, runtime_cleanup):
    """A stop event delivered after a restart re-created the domain must not
    clean up the freshly started, still-running instance nor unmount its runtime
    state."""
    manager = DomainManager(mock_connection)
    tracked = Mock()  # the newly started StartedDomain
    manager.started_domains["uuid-1"] = tracked

    mock_connection.get_domain.return_value = Mock()  # domain exists...
    mock_connection.domain_state.return_value = DomainState.RUNNING  # ...and is running

    manager._domain_event_callback(_event("uuid-1", VirDomainEvent.STOPPED))

    assert manager.started_domains["uuid-1"] is tracked
    tracked.cleanup.assert_not_called()
    runtime_cleanup.assert_not_called()


def test_stop_event_for_stopped_domain_cleans_up(mock_connection, runtime_cleanup):
    """A genuine stop (domain now SHUTOFF) cleans up tracking and reconciles
    durable runtime state."""
    manager = DomainManager(mock_connection)
    tracked = Mock()
    manager.started_domains["uuid-1"] = tracked

    mock_connection.get_domain.return_value = Mock()
    mock_connection.domain_state.return_value = DomainState.SHUTOFF

    manager._domain_event_callback(_event("uuid-1", VirDomainEvent.STOPPED))

    assert "uuid-1" not in manager.started_domains
    tracked.cleanup.assert_called_once()
    runtime_cleanup.assert_called_once_with("uuid-1")


def test_undefined_event_with_missing_domain_cleans_up(mock_connection, runtime_cleanup):
    """An UNDEFINED event (domain gone, get_domain() -> None) must still clean
    up, not skip because the domain lookup returned None."""
    manager = DomainManager(mock_connection)
    tracked = Mock()
    manager.started_domains["uuid-1"] = tracked

    mock_connection.get_domain.return_value = None

    manager._domain_event_callback(_event("uuid-1", VirDomainEvent.UNDEFINED))

    assert "uuid-1" not in manager.started_domains
    tracked.cleanup.assert_called_once()
    runtime_cleanup.assert_called_once_with("uuid-1")


def test_stop_event_when_domain_vanishes_mid_state_query_cleans_up(mock_connection, runtime_cleanup):
    """The domain can be undefined between get_domain() and the state query;
    VIR_ERR_NO_DOMAIN there means gone, so clean up as for a missing domain."""
    manager = DomainManager(mock_connection)
    tracked = Mock()
    manager.started_domains["uuid-1"] = tracked

    mock_connection.get_domain.return_value = Mock()  # still there at lookup...
    mock_connection.domain_state.side_effect = _libvirt_error(libvirt.VIR_ERR_NO_DOMAIN)  # ...gone at query

    manager._domain_event_callback(_event("uuid-1", VirDomainEvent.STOPPED))

    assert "uuid-1" not in manager.started_domains
    tracked.cleanup.assert_called_once()
    runtime_cleanup.assert_called_once_with("uuid-1")


def test_stop_event_with_other_libvirt_error_propagates_without_cleanup(mock_connection, runtime_cleanup):
    """A state-query failure other than NO_DOMAIN says nothing about whether the
    domain is stopped, so it must propagate rather than trigger teardown of a
    possibly-running domain."""
    manager = DomainManager(mock_connection)
    tracked = Mock()
    manager.started_domains["uuid-1"] = tracked

    mock_connection.get_domain.return_value = Mock()
    mock_connection.domain_state.side_effect = _libvirt_error(libvirt.VIR_ERR_INTERNAL_ERROR)

    with pytest.raises(libvirt.libvirtError):
        manager._domain_event_callback(_event("uuid-1", VirDomainEvent.STOPPED))

    assert manager.started_domains["uuid-1"] is tracked
    tracked.cleanup.assert_not_called()
    runtime_cleanup.assert_not_called()


def test_non_stop_event_is_ignored(mock_connection, runtime_cleanup):
    """Non-stop events (e.g. STARTED) do nothing and never query libvirt."""
    manager = DomainManager(mock_connection)
    tracked = Mock()
    manager.started_domains["uuid-1"] = tracked

    manager._domain_event_callback(_event("uuid-1", VirDomainEvent.STARTED))

    assert manager.started_domains["uuid-1"] is tracked
    tracked.cleanup.assert_not_called()
    runtime_cleanup.assert_not_called()
    mock_connection.get_domain.assert_not_called()
