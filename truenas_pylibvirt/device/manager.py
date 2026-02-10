from __future__ import annotations

from contextlib import ExitStack, contextmanager
import logging
from typing import TYPE_CHECKING, Generator, Self


if TYPE_CHECKING:
    from .base import Device
    from ..libvirtd.connection import Connection


logger = logging.getLogger(__name__)


class StartedDevice:
    def __init__(self, device: Device, connection: Connection, domain_uuid: str) -> None:
        self.connection = connection
        self.device = device
        self.exit_stack = ExitStack()
        self.context = self.exit_stack.enter_context(self.device.run(connection, domain_uuid))

    def cleanup(self) -> None:
        self.exit_stack.close()


class DeviceManager:
    def __init__(self, devices: list[Device], domain_uuid: str) -> None:
        self.devices: list[Device] = devices
        self.domain_uuid = domain_uuid

    @contextmanager
    def start(self, connection: Connection) -> Generator[Self, None, None]:
        started_devices = []

        try:
            for device in self.devices:
                try:
                    started = StartedDevice(device, connection, self.domain_uuid)
                    started_devices.append(started)
                except Exception as e:
                    logger.error(f'Failed to start device {device.identity()}: {e}', exc_info=True)
                    for started_device in reversed(started_devices):
                        try:
                            started_device.cleanup()
                        except Exception as cleanup_error:
                            logger.error(
                                f'Failed to cleanup device during startup rollback: {cleanup_error}', exc_info=True
                            )
                    raise

            yield self

        finally:
            for started_device in reversed(started_devices):
                try:
                    started_device.cleanup()
                except Exception as e:
                    device_id = started_device.device.identity()
                    logger.error(f'Failed to cleanup device {device_id}: {e}', exc_info=True)
