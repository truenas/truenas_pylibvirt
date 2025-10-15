"""Shared fixtures for pylibvirt tests."""
from __future__ import annotations

import pytest
from unittest.mock import Mock, MagicMock


@pytest.fixture
def mock_connection():
    """Mock Connection object for testing."""
    conn = Mock()
    conn.connection = MagicMock()
    conn.domain_state = Mock(return_value=Mock(value='RUNNING'))
    conn.get_domain = Mock()
    conn.list_domains = Mock(return_value=[])
    return conn


@pytest.fixture
def device_context():
    """Device XML generation context with counters."""
    from truenas_pylibvirt.device.counters import Counters
    from truenas_pylibvirt.device.base import DeviceXmlContext
    return DeviceXmlContext(counters=Counters())


@pytest.fixture
def start_context(mock_connection):
    """Start validation context for testing device validation."""
    from truenas_pylibvirt.domain.start_validator import StartValidationContext
    return StartValidationContext(
        connection=mock_connection,
        domain_uuid="test-uuid-12345"
    )


@pytest.fixture
def mock_device_delegate():
    """Mock device delegate for testing."""
    from truenas_pylibvirt.device.delegate import DeviceDelegate

    delegate = Mock(spec=DeviceDelegate)
    delegate.is_available = Mock(return_value=True)
    return delegate
