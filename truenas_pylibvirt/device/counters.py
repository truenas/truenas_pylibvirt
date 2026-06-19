from __future__ import annotations

from collections import defaultdict
from itertools import count


class Counters:
    def __init__(self) -> None:
        self._boot_no = count(1)
        self._scsi_device_no = count(1)
        self._usb_controller_no = count(1)
        # The display device emits the nec-xhci controller and libvirt assigns it index 0, so we
        # seed our mapping accordingly and never emit a nec-xhci controller from a USB device.
        self._usb_controllers_no = defaultdict(lambda: next(self._usb_controller_no))
        self._usb_controllers_no["nec-xhci"] = 0
        self._emitted_usb_controllers: set[str] = set()
        self._virtual_device_no = count(1)

    def next_boot_no(self) -> int:
        return next(self._boot_no)

    def next_scsi_device_no(self) -> int:
        return next(self._scsi_device_no)

    def usb_controller_no(self, type_: str) -> int:
        return self._usb_controllers_no[type_]

    def should_emit_usb_controller(self, type_: str) -> bool:
        # A single USB controller hosts many devices, so its <controller> element must be
        # emitted only once per type. Returns True the first time a type is seen and False
        # afterwards, letting subsequent devices of the same type share the controller.
        if type_ in self._emitted_usb_controllers:
            return False
        self._emitted_usb_controllers.add(type_)
        return True

    def next_virtual_device_no(self) -> int:
        return next(self._virtual_device_no)
