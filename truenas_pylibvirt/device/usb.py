from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

from ..error import DeviceNotFoundError
from ..xml import xml_element
from .base import Device, DeviceXmlContext
from ..utils.usb import find_usb_device_by_libvirt_name, find_usb_device_by_ids


@dataclass(kw_only=True)
class USBDevice(Device):

    EXCLUSIVE_DEVICE = True  # USB devices can only be used by one VM at a time

    vendor_id: str | None
    product_id: str | None
    device: str | None
    controller_type: str | None

    def xml(self, context: DeviceXmlContext) -> list[ElementTree.Element]:
        capability = self.resolve()['capability']
        children = [
            xml_element(
                "source",
                children=[
                    xml_element("vendor", attributes={"id": capability['vendor_id']}),
                    xml_element("product", attributes={"id": capability['product_id']}),
                    xml_element(
                        "address", attributes={
                            "bus": capability['bus'], "device": capability['device'],
                        }
                    ),
                ],
            ),
        ]
        bus_no = None
        if self.controller_type:
            bus_no = context.counters.usb_controller_no(self.controller_type)
            children.append(
                xml_element(
                    "address",
                    attributes={
                        "type": "usb",
                        "bus": str(bus_no),
                    },
                ),
            )

        controllers = []
        # The nec-xhci controller at index 0 is supplied by the display device (or, lacking one,
        # auto-added by libvirt), so a USB device never emits it itself. For other types the
        # controller is emitted once and shared by every device of that type; emitting it per
        # device produces duplicate controllers that libvirt rejects with "Duplicate USB
        # controllers with index N".
        if (
            self.controller_type
            and self.controller_type != 'nec-xhci'
            and context.counters.should_emit_usb_controller(self.controller_type)
        ):
            controllers.append(
                xml_element(
                    "controller",
                    attributes={
                        "type": "usb",
                        "index": str(bus_no),
                        "model": self.controller_type,
                    },
                )
            )

        return [
            xml_element(
                "hostdev",
                attributes={
                    "mode": "subsystem",
                    "type": "usb",
                    "managed": "yes",
                },
                children=children,
            ),
            *controllers,
        ]

    def identity_impl(self) -> str:
        return self.device or f"{self.product_id}--{self.vendor_id}"

    def resolve(self) -> dict[str, Any]:
        """
        Live details of the configured USB device.

        The bus and device numbers written into the domain XML are whatever the kernel has
        assigned right now, so they are read here rather than taken from configuration. A device
        that cannot be resolved raises: a domain that quietly starts without a passthrough device
        it was configured with is indistinguishable, from every surface we expose, from one that
        got it.
        """
        details = self.get_usb_details()
        if details is None or details.get('error'):
            raise DeviceNotFoundError(self.not_found_message())

        return details

    def not_found_message(self) -> str:
        if self.device:
            return (
                f'No USB device is connected at {self.device}. Plug the device back into the same '
                'port, or reconfigure this VM to use the port it is now plugged into.'
            )

        return (
            f'No USB device with vendor ID {self.vendor_id} and product ID {self.product_id} is '
            'connected to this system.'
        )

    def get_usb_details(self) -> dict[str, Any] | None:
        if self.device:
            return find_usb_device_by_libvirt_name(self.device)
        elif self.vendor_id and self.product_id:
            device_name = find_usb_device_by_ids(self.vendor_id, self.product_id)
            if device_name:
                return find_usb_device_by_libvirt_name(device_name)
        return None

    def is_available_impl(self) -> bool:
        details = self.get_usb_details()
        if details is None:
            return False

        return details.get("available", False) and not details.get("error")

    def validate_impl(self) -> list[tuple[str, str]]:
        verrors = []
        if self.device and (self.product_id or self.vendor_id):
            verrors.append(
                ("device", "Either device must be specified or USB details but not both")
            )
        elif not self.device and not (self.product_id or self.vendor_id):
            verrors.append(
                (
                    "usb",
                    "Either device or product_id and vendor_id  must be specified"
                )
            )

        usb_device_details = self.get_usb_details()
        if not usb_device_details or usb_device_details.get("error"):
            # Same wording the start path uses, so what the user is told when configuring the
            # device and what they are told when it fails to start cannot drift apart.
            verrors.append(("device" if self.device else "usb", self.not_found_message()))

        return verrors

    def _is_device_in_domain_xml(self, domain_xml_root: ElementTree.Element) -> bool:
        """Check if this USB device is present in the domain XML"""
        for hostdev in domain_xml_root.findall(".//devices/hostdev[@type='usb']"):
            # Check by vendor/product ID
            if self.vendor_id and self.product_id:
                vendor = hostdev.find(".//source/vendor")
                product = hostdev.find(".//source/product")
                if (vendor is not None and vendor.get("id") == self.vendor_id and
                        product is not None and product.get("id") == self.product_id):
                    return True

            # Check by device
            if self.device:
                address = hostdev.find(".//source/address")
                if address is not None and address.get("device") == self.device:
                    return True

        return False
