from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
import logging
from typing import Generator, TYPE_CHECKING
from xml.etree import ElementTree

import libvirt

from .counters import Counters
from .delegate import DeviceDelegate


if TYPE_CHECKING:
    from ..domain.start_validator import StartValidationContext
    from ..libvirtd.connection import Connection

logger = logging.getLogger(__name__)


@dataclass
class DeviceXmlContext:
    counters: Counters


@dataclass(kw_only=True)
class Device(ABC):

    device_delegate: DeviceDelegate = field(default_factory=DeviceDelegate)

    # Override in subclasses that require exclusive access (can only be used by one VM at a time)
    EXCLUSIVE_DEVICE = False

    def __post_init__(self) -> None:
        if self.device_delegate is None:
            raise TypeError('Device delegate must not be None')

    @abstractmethod
    def xml(self, context: DeviceXmlContext) -> list[ElementTree.Element]:
        ...

    @contextmanager
    def run(self, connection: Connection, domain_uuid: str) -> Generator[None, None, None]:
        yield

    def is_available(self) -> bool:
        return self.device_delegate.is_available(self) and self.is_available_impl()

    @abstractmethod
    def is_available_impl(self) -> bool:
        ...

    def identity(self) -> str:
        return self.identity_impl()

    @abstractmethod
    def identity_impl(self) -> str:
        ...

    def validate(self) -> list[tuple[str, str]]:
        return self.validate_impl()

    def validate_impl(self) -> list[tuple[str, str]]:
        return []

    def validate_start(self, context: StartValidationContext) -> list[tuple[str, str]]:
        """
        Validate device can be started.
        This is different from validate() which validates configuration.
        """
        errors = []

        # Check for exclusive device conflicts if this device requires it
        if self.EXCLUSIVE_DEVICE:
            in_use, vm_name = self._is_in_use_by_other_vms(
                context.connection,
                context.domain_uuid
            )
            if in_use:
                device_type = self.__class__.__name__.replace('Device', '')
                errors.append((
                    f'device.{self.identity()}',
                    f'{device_type} device is already in use by VM {vm_name}'
                ))

        # Add any device-specific validation
        errors.extend(self.validate_start_impl(context))
        return errors

    def validate_start_impl(self, context: StartValidationContext) -> list[tuple[str, str]]:
        """Override in subclasses for device-specific start validation beyond exclusivity checks"""
        return []

    def _is_in_use_by_other_vms(self, connection: Connection, exclude_domain_uuid: str) -> tuple[bool, str | None]:
        """
        Check if device is used by any other running VM.
        Returns: (is_in_use, vm_name_using_it)
        """
        try:
            # List all domains
            for domain in connection.connection.listAllDomains():
                # Skip ourselves
                if domain.UUIDString() == exclude_domain_uuid:
                    continue

                # Only check active VMs
                if not domain.isActive():
                    continue

                # Get domain XML and let subclass check for conflicts
                xml_str = domain.XMLDesc()
                root = ElementTree.fromstring(xml_str)

                if self._is_device_in_domain_xml(root):
                    return True, domain.name()

            return False, None

        except libvirt.libvirtError as e:
            # Log error but don't fail - device might still work
            logger.warning(f"Failed to check device conflicts: {e}")
            return False, None

    def _is_device_in_domain_xml(self, domain_xml_root: ElementTree.Element) -> bool:
        """
        Override to check if this device is present in the domain XML.
        Child classes should implement this method and return True if the device is found.
        """
        return False
