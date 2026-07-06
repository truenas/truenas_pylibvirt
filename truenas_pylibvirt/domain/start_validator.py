from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from ..device.base import Device
    from ..libvirtd.connection import Connection


@dataclass
class StartValidationContext:
    """Context for start validation - can be extended by consumers"""
    connection: Connection
    domain_uuid: str


def check_pci_slot_conflicts(devices: list[Device]) -> list[tuple[str, str]]:
    """Return (field, error) pairs for any two devices claiming the same (bus, slot).

    Only devices that return a non-None pci_slot() participate in the check.
    """
    seen: dict[tuple[int, int], str] = {}
    errors = []
    for device in devices:
        slot = device.pci_slot()
        if slot is None:
            continue
        identity = device.identity()
        if slot in seen:
            errors.append((
                f'device.{identity}',
                f'PCI bus {slot[0]} slot {slot[1]} already claimed by {seen[slot]}',
            ))
        else:
            seen[slot] = identity
    return errors


class StartValidator:
    """Validates domain can start - checks for conflicts, availability, etc."""

    def validate(self, devices: list[Device], context: StartValidationContext) -> list[tuple[str, str]]:
        """
        Perform pre-start validation checks.
        Returns list of (field, error) tuples.
        """
        errors = []

        for device in devices:
            if not device.is_available():
                errors.append((
                    f'device.{device.identity()}',
                    f'Device {device.identity()} is not available'
                ))

            device_errors = device.validate_start(context)
            errors.extend(device_errors)

        errors.extend(check_pci_slot_conflicts(devices))

        return errors
