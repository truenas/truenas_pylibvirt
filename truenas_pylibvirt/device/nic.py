from __future__ import annotations

import enum
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from truenas_pynetif.address.netlink import get_default_route, link_exists, netlink_route
from truenas_pynetif.bits import InterfaceFlags
from truenas_pynetif.netif import get_interface

from ..xml import xml_element
from .base import Device, DeviceXmlContext


if TYPE_CHECKING:
    from ..libvirtd.connection import Connection


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
                            xml_element("source", attributes={"bridge": self.identity()}),
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
                            xml_element("source", attributes={"dev": self.identity(), "mode": "bridge"}),
                            *children,
                        ],
                    )
                ]

    @contextmanager
    def run(self, connection: Connection, domain_uuid: str):
        if (nic := get_interface(self.identity(), True)) and nic and InterfaceFlags.UP not in nic.flags:
            nic.up()

        yield

    def is_available_impl(self) -> bool:
        return link_exists(self.identity())

    def identity_impl(self) -> str:
        nic_attach = self.source
        if not nic_attach:
            with netlink_route() as sock:
                if default_route := get_default_route(sock):
                    nic_attach = default_route.oif_name
        return nic_attach

    def validate_impl(self) -> list[tuple[str, str]]:
        verrors = []
        if self.source and self.source.startswith('br') and self.trust_guest_rx_filters:
            verrors.append(
                ('trust_guest_rx_filters', 'This can only be set when "nic_attach" is not a bridge device')
            )

        if self.trust_guest_rx_filters and self.model == NICDeviceModel.E1000:
            verrors.append(
                ('trust_guest_rx_filters', 'This can only be set when "type" of NIC device is "VIRTIO"')
            )

        if self.mac and self.mac.lower().startswith('ff'):
            verrors.append(
                ('mac', 'MAC address must not start with `ff`')
            )
        return verrors
