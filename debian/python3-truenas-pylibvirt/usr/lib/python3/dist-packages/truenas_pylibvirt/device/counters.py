from collections import defaultdict
from itertools import count


class Counters:
    def __init__(self):
        self._boot_no = count(1)
        self._scsi_device_no = count(1)
        self._usb_controller_no = count(1)
        # nec-xhci is added by default for each domain by libvirt so we update our mapping accordingly
        self._usb_controllers_no = defaultdict(lambda: next(self._usb_controller_no))
        self._usb_controllers_no["nec-xhci"] = 0
        self._virtual_device_no = count(1)

    def next_boot_no(self):
        return next(self._boot_no)

    def next_scsi_device_no(self):
        return next(self._scsi_device_no)

    def usb_controller_no(self, type_: str):
        return self._usb_controllers_no[type_]

    def next_virtual_device_no(self):
        return next(self._virtual_device_no)
