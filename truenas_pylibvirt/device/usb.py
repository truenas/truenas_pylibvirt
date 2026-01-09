from dataclasses import dataclass

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

    def xml(self, context: DeviceXmlContext):
        capability = self.get_usb_details()['capability']
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
        if self.controller_type:
            children.append(
                xml_element(
                    "address",
                    attributes={
                        "type": "usb",
                        "bus": str(context.counters.usb_controller_no(self.controller_type)),
                    },
                ),
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
            *(
                [
                    xml_element(
                        "controller",
                        attributes={
                            "type": "usb",
                            "index": str(context.counters.usb_controller_no(self.controller_type)),
                            "model": self.controller_type
                        }
                    )
                ] if self.controller_type and self.controller_type != 'nec-xhci' else []
            )
        ]

    def identity_impl(self) -> str:
        return self.device or f"{self.product_id}--{self.vendor_id}"

    def get_usb_details(self) -> dict | None:
        if self.device:
            return find_usb_device_by_libvirt_name(self.device)
        elif self.vendor_id and self.product_id:
            device_name = find_usb_device_by_ids(self.vendor_id, self.product_id)
            if device_name:
                return find_usb_device_by_libvirt_name(device_name)
        return None

    def is_available_impl(self) -> bool:
        details = self.get_usb_details()
        return details.get("available", False) and not details.get("error") if details else False

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
        if self.device:
            if not usb_device_details:
                verrors.append(("device", f"No USB device found with name {self.device}"))
            elif usb_device_details.get("error"):
                verrors.append(("device", usb_device_details["error"]))
        else:
            if not usb_device_details:
                verrors.append(
                    (
                        "usb",
                        f"No USB device found with Vendor ID {self.vendor_id} and Product ID {self.product_id}"
                    )
                )
            elif usb_device_details.get("error"):
                verrors.append(("usb", usb_device_details["error"]))

        return verrors

    def _is_device_in_domain_xml(self, domain_xml_root) -> bool:
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
