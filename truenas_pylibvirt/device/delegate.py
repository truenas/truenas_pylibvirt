from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from .base import Device


class DeviceDelegate:

    def is_available(self, device: Device) -> bool:
        return True
