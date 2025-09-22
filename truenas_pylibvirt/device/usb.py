from ..xml import xml_element
from .base import Device, DeviceXmlContext


class USBDevice(Device):
    vendor_id: str
    product_id: str
    bus: str
    device: str
    controller_type: str

    def xml(self, context: DeviceXmlContext):
        return [
            xml_element(
                "hostdev",
                attributes={
                    "mode": "subsystem",
                    "type": "usb",
                    "managed": "yes",
                },
                children=[
                    xml_element(
                        "source",
                        children=[
                            xml_element("vendor", attributes={"id": self.vendor_id}),
                            xml_element("product", attributes={"id": self.product_id}),
                            xml_element("address", attributes={"bus": self.bus, "device": self.device}),
                        ],
                    ),
                    xml_element(
                        "address",
                        attributes={
                            "type": "usb",
                            "bus": str(context.counters.usb_controller_no(self.controller_type)),
                        },
                    ),
                ],
            ),
        ]
