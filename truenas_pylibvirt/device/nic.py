from contextlib import contextmanager
import enum

from ..xml import xml_element
from .base import Device, DeviceXmlContext


class NICDeviceType(enum.Enum):
    E1000 = "E1000"
    VIRTIO = "VIRTIO"


class NICDevice(Device):
    trust_guest_rx_filters: bool
    type_: NICDeviceType
    nic_attach: str | None
    mac: str | None

    def xml(self, context: DeviceXmlContext):
        children = [
            xml_element("model", attributes={"type": self.type_.value.lower()}),
            xml_element(
                "mac",
                attributes={"address": self.mac},
            ),
        ]

        if self.nic_attach.startswith("br"):
            return [
                xml_element(
                    "interface",
                    attributes={"type": "bridge"},
                    children=[
                        xml_element("source", attributes={"bridge": self.nic_attach}),
                        *children,
                    ],
                ),
            ]
        else:
            trust_guest_rx_filters = "yes" if self.trust_guest_rx_filters else "no"
            return [
                xml_element(
                    "interface",
                    attributes={"type": "direct", "trustGuestRxFilters" :trust_guest_rx_filters},
                    children=[
                        xml_element("source", attributes={"dev": "self.nic_attach", "mode": "bridge"}),
                        *children,
                    ],
                )
            ]
