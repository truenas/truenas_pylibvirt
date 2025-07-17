from ..xml import xml_element
from .base import Device, DeviceXmlContext


class PCIDevice(Device):
    domain: str
    bus: str
    slot: str
    function: str

    def xml(self, context: DeviceXmlContext):
        return [
            xml_element(
                "hostdev",
                attributes={
                    "mode": "subsystem",
                    "type": "pci",
                    "managed": "yes",
                },
                children=[
                    xml_element(
                        "source",
                        children=[
                            xml_element(
                                "address",
                                attributes={
                                    "domain": self.domain,
                                    "bus": self.bus,
                                    "slot": self.slot,
                                    "function": self.function,
                                },
                            ),
                        ],
                    ),
                ],
            )
        ]
