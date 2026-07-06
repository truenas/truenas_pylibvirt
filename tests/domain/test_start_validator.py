"""Tests for domain start validation."""
from __future__ import annotations

from unittest.mock import Mock

from truenas_pylibvirt.domain.start_validator import StartValidator, StartValidationContext, check_pci_slot_conflicts
from truenas_pylibvirt.device.manager import DeviceManager


def test_start_validator_validates_all_devices(mock_connection, mock_device_delegate):
    """Test that start validator calls validate_start on all devices."""
    # Create some mock devices
    device1 = Mock()
    device1.is_available.return_value = True
    device1.validate_start.return_value = []

    device2 = Mock()
    device2.is_available.return_value = True
    device2.validate_start.return_value = []

    # Create domain with device manager
    mock_domain = Mock()
    device_manager = DeviceManager(devices=[device1, device2], domain_uuid="test-uuid")
    mock_domain.device_manager = device_manager

    validator = StartValidator()
    context = StartValidationContext(
        connection=mock_connection,
        domain_uuid="test-uuid"
    )

    errors = validator.validate(mock_domain.device_manager.devices, context)

    # Verify both devices were validated
    assert device1.validate_start.called
    assert device2.validate_start.called
    assert len(errors) == 0


def test_start_validator_detects_unavailable_device(mock_connection):
    """Test that start validator detects unavailable devices."""
    # Create a device that's not available
    device = Mock()
    device.is_available.return_value = False
    device.identity.return_value = "test-device-id"
    device.validate_start.return_value = []

    # Create domain with device manager
    mock_domain = Mock()
    device_manager = DeviceManager(devices=[device], domain_uuid="test-uuid")
    mock_domain.device_manager = device_manager

    validator = StartValidator()
    context = StartValidationContext(
        connection=mock_connection,
        domain_uuid="test-uuid"
    )

    errors = validator.validate(mock_domain.device_manager.devices, context)

    # Should report device as unavailable
    assert len(errors) == 1
    assert "test-device-id" in errors[0][0]
    assert "not available" in errors[0][1]


def test_start_validator_accumulates_errors(mock_connection):
    """Test that start validator accumulates errors from all devices."""
    # Create devices with different errors
    device1 = Mock()
    device1.is_available.return_value = False
    device1.identity.return_value = "device1"
    device1.validate_start.return_value = []

    device2 = Mock()
    device2.is_available.return_value = True
    device2.validate_start.return_value = [("field", "error message")]

    # Create domain with device manager
    mock_domain = Mock()
    device_manager = DeviceManager(devices=[device1, device2], domain_uuid="test-uuid")
    mock_domain.device_manager = device_manager

    validator = StartValidator()
    context = StartValidationContext(
        connection=mock_connection,
        domain_uuid="test-uuid"
    )

    errors = validator.validate(mock_domain.device_manager.devices, context)

    # Should have errors from both devices
    assert len(errors) == 2


def test_check_pci_slot_conflicts_no_conflict():
    """Devices on distinct (bus, slot) pairs produce no errors."""
    d1 = Mock()
    d1.pci_slot.return_value = (0, 5)
    d1.identity.return_value = "dev1"
    d2 = Mock()
    d2.pci_slot.return_value = (0, 6)
    d2.identity.return_value = "dev2"
    assert check_pci_slot_conflicts([d1, d2]) == []


def test_check_pci_slot_conflicts_same_slot():
    """Two devices claiming the same (bus, slot) produce an error naming both
    the conflicting device and the one that already holds the slot."""
    d1 = Mock()
    d1.pci_slot.return_value = (0, 5)
    d1.identity.return_value = "dev1"
    d2 = Mock()
    d2.pci_slot.return_value = (0, 5)
    d2.identity.return_value = "dev2"
    errors = check_pci_slot_conflicts([d1, d2])
    assert len(errors) == 1
    assert "dev2" in errors[0][0]
    assert "bus 0" in errors[0][1] and "slot 5" in errors[0][1]
    assert "dev1" in errors[0][1]


def test_check_pci_slot_conflicts_different_buses():
    """The same slot number on different buses is not a conflict."""
    d1 = Mock()
    d1.pci_slot.return_value = (0, 5)
    d1.identity.return_value = "dev1"
    d2 = Mock()
    d2.pci_slot.return_value = (1, 5)
    d2.identity.return_value = "dev2"
    assert check_pci_slot_conflicts([d1, d2]) == []


def test_check_pci_slot_conflicts_none_excluded():
    """Devices returning None from pci_slot() are excluded from conflict checks."""
    d1 = Mock()
    d1.pci_slot.return_value = None
    d2 = Mock()
    d2.pci_slot.return_value = None
    assert check_pci_slot_conflicts([d1, d2]) == []


def test_start_validator_reports_pci_slot_conflict(mock_connection):
    """StartValidator.validate() includes PCI slot conflicts alongside other
    per-device errors."""
    d1 = Mock()
    d1.is_available.return_value = True
    d1.validate_start.return_value = []
    d1.pci_slot.return_value = (0, 5)
    d1.identity.return_value = "dev1"
    d2 = Mock()
    d2.is_available.return_value = True
    d2.validate_start.return_value = []
    d2.pci_slot.return_value = (0, 5)
    d2.identity.return_value = "dev2"

    validator = StartValidator()
    context = StartValidationContext(connection=mock_connection, domain_uuid="test-uuid")
    errors = validator.validate([d1, d2], context)
    assert any("slot 5" in e[1] for e in errors)
