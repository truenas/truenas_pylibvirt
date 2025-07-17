from dataclasses import dataclass
import enum

from ..xml import xml_element
from .base import Device, DeviceXmlContext


class NICDeviceType(enum.Enum):
    BRIDGE = "BRIDGE"
    DIRECT = "DIRECT"


class NICDeviceModel(enum.Enum):
    E1000 = "E1000"
    VIRTIO = "VIRTIO"


@dataclass(kw_only=True)
class NICDevice(Device):
    type_: NICDeviceType
    source: str
    model: NICDeviceModel | None
    mac: str | None
    trust_guest_rx_filters: bool

    def xml(self, context: DeviceXmlContext):
        children = []
        if self.model:
            children.append(xml_element("model", attributes={"type": self.model.value.lower()}))
        if self.mac:
            children.append(xml_element("mac", attributes={"address": self.mac}))

        match self.type_:
            case NICDeviceType.BRIDGE:
                return [
                    xml_element(
                        "interface",
                        attributes={"type": "bridge"},
                        children=[
                            xml_element("source", attributes={"bridge": self.source}),
                            *children,
                        ],
                    ),
                ]

            case NICDeviceType.DIRECT:
                trust_guest_rx_filters = "yes" if self.trust_guest_rx_filters else "no"
                return [
                    xml_element(
                        "interface",
                        attributes={"type": "direct", "trustGuestRxFilters": trust_guest_rx_filters},
                        children=[
                            xml_element("source", attributes={"dev": self.source, "mode": "bridge"}),
                            *children,
                        ],
                    )
                ]
