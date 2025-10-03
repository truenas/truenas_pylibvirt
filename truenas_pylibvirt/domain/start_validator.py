from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from .base.domain import BaseDomain
    from ..libvirtd.connection import Connection


@dataclass
class StartValidationContext:
    """Context for start validation - can be extended by consumers"""
    connection: Connection
    domain_uuid: str


class StartValidator:
    """Validates domain can start - checks for conflicts, availability, etc."""

    def validate(self, domain: BaseDomain, context: StartValidationContext) -> list[tuple[str, str]]:
        """
        Perform pre-start validation checks.
        Returns list of (field, error) tuples.
        """
        errors = []

        for device in domain.device_manager.devices:
            if not device.is_available():
                errors.append((
                    f'device.{device.identity()}',
                    f'Device {device.identity()} is not available'
                ))

            device_errors = device.validate_start(context)
            errors.extend(device_errors)

        return errors
