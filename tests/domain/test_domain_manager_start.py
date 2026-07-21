"""Regression tests for DomainManager.start()'s handling of a domain that is
already present in `started_domains`.

The dangerous case is a second start() on a domain that is still running: the
entry must stay tracked and must NOT be cleaned up. Dropping it there leaves its
ExitStack to garbage collection, whose device finalizers terminate the display
proxy and unmount a running container's bind mounts (libvirt refuses the managed
PCI reattach while the device is still assigned to the running domain).
"""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from truenas_pylibvirt.domain.manager import DomainManager
from truenas_pylibvirt.libvirtd.connection import DomainState
from truenas_pylibvirt.error import Error


def _domain(uuid: str = "uuid-1", name: str = "testvm") -> Mock:
    domain = Mock()
    domain.configuration.uuid = uuid
    domain.configuration.name = name
    domain.device_manager.devices = []
    return domain


@pytest.mark.parametrize("active_state", [DomainState.RUNNING, DomainState.PAUSED])
def test_start_on_active_domain_keeps_tracking_and_does_not_clean_up(mock_connection, active_state):
    """A second start() on an already-active tracked domain raises, keeps the
    entry in started_domains, and never tears down its staging."""
    manager = DomainManager(mock_connection)
    domain = _domain()

    tracked = Mock()  # stand-in for the live StartedDomain
    manager.started_domains[domain.configuration.uuid] = tracked

    mock_connection.get_domain.return_value = Mock()  # libvirt still has the domain
    mock_connection.domain_state.return_value = active_state

    with pytest.raises(Error, match="already started"):
        manager.start(domain)

    # Still tracked (so the eventual STOPPED event can clean it up), never GC-leaked.
    assert manager.started_domains[domain.configuration.uuid] is tracked
    tracked.cleanup.assert_not_called()


def test_start_when_libvirt_domain_missing_cleans_up_stale_entry(mock_connection):
    """A tracked entry whose libvirt domain has vanished (get_domain() -> None)
    is cleaned up and removed explicitly, not silently dropped to GC."""
    manager = DomainManager(mock_connection)
    domain = _domain()

    stale = Mock()
    manager.started_domains[domain.configuration.uuid] = stale

    mock_connection.get_domain.return_value = None
    # Short-circuit right after the stale-entry handling so the full define/create
    # tail does not need mocking.
    manager.start_validator.validate = Mock(return_value=[("field", "boom")])

    with pytest.raises(Error, match="Cannot start"):
        manager.start(domain)

    stale.cleanup.assert_called_once()
    assert domain.configuration.uuid not in manager.started_domains


def test_start_when_tracked_but_stopped_cleans_up_and_removes(mock_connection):
    """A tracked entry whose domain is actually stopped is cleaned up and removed
    before the start proceeds (here short-circuited at validation)."""
    manager = DomainManager(mock_connection)
    domain = _domain()

    stale = Mock()
    manager.started_domains[domain.configuration.uuid] = stale

    mock_connection.get_domain.return_value = Mock()
    mock_connection.domain_state.return_value = DomainState.SHUTOFF
    manager.start_validator.validate = Mock(return_value=[("field", "boom")])

    with pytest.raises(Error, match="Cannot start"):
        manager.start(domain)

    stale.cleanup.assert_called_once()
    assert domain.configuration.uuid not in manager.started_domains
