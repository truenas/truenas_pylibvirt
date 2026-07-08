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


def pci_slot_error_for_machine(slot: int, machine_type: str | None) -> str | None:
    """Return an error string if slot violates the machine topology PCI slot rules, else None.

    PCIe (q35 / aarch64 virt): ports are point-to-point, so slot must be 0.
    i440fx (PCI bridge): slot 0 is the SHPC controller; usable slots start at 1.
    Unknown machine type is treated conservatively as i440fx.
    """
    mt = machine_type or ''
    is_pcie = 'q35' in mt or mt.startswith('virt')
    if is_pcie and slot != 0:
        return 'PCIe machines (q35 / aarch64 virt) use point-to-point ports; slot must be 0'
    if not is_pcie and slot == 0:
        return 'Slot 0 is reserved (SHPC controller) on i440fx PCI bridges; usable slots start at 1'
    return None


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
