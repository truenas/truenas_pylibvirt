from __future__ import annotations

from contextlib import ExitStack
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from .base import Device
    from ..libvirtd.connection import Connection


class StartedDevice:
    def __init__(self, device: Device, connection: Connection, domain_uuid: str):
        self.connection = connection
        self.device = device
        self.exit_stack = ExitStack()
        self.context = self.exit_stack.enter_context(self.device.run(connection, domain_uuid))

    def cleanup(self):
        self.exit_stack.close()


class DeviceManager:

    def __init__(self, devices: list[Device], domain_uuid: str):
        self.devices: list[Device] = devices
        self.started_devices: list[StartedDevice] = []
        self.connection: Connection | None = None
        self.domain_uuid = domain_uuid

    def set_connection(self, connection: Connection):
        self.connection = connection

    def start_devices(self):
        assert self.connection is not None
        for device in self.devices:
            self.started_devices.append(StartedDevice(device, self.connection, self.domain_uuid))

    def cleanup_devices(self):
        """Cleanup all started devices in reverse order"""
        for started_device in reversed(self.started_devices):
            started_device.cleanup()
        self.started_devices.clear()
