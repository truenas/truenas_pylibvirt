from __future__ import annotations

import enum
import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generator
from xml.etree import ElementTree

from truenas_pynetif.address.get_links import get_link
from truenas_pynetif.address.link import set_link_up
from truenas_pynetif.address.netlink import get_default_route, netlink_route
from truenas_pynetif.bits import InterfaceFlags
from truenas_pynetif.netlink import DeviceNotFound

from ..xml import xml_element
from .base import Device, DeviceXmlContext


if TYPE_CHECKING:
    from ..libvirtd.connection import Connection


# libvirt's defineXML only parses colon-separated MAC addresses.
MAC_ADDRESS_RE = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')


class NICDeviceType(enum.Enum):
    BRIDGE = "BRIDGE"
    DIRECT = "DIRECT"


class NICDeviceModel(enum.Enum):
    E1000 = "E1000"
    VIRTIO = "VIRTIO"


@dataclass
class PciAddress:
    bus: int
    slot: int
    function: int = 0
    domain: int = 0

    def to_xml_element(self) -> ElementTree.Element:
        return xml_element("address", attributes={
            "type": "pci",
            "domain": f"0x{self.domain:04x}",
            "bus": f"0x{self.bus:02x}",
            "slot": f"0x{self.slot:02x}",
            "function": f"0x{self.function:x}",
        })


@dataclass(kw_only=True)
class NICDevice(Device):

    type_: NICDeviceType
    source: str
    model: NICDeviceModel | None
    mac: str | None
    trust_guest_rx_filters: bool
    pci_address: PciAddress | None = None

    def xml(self, context: DeviceXmlContext) -> list[ElementTree.Element]:
        children = []
        if self.model:
            children.append(xml_element("model", attributes={"type": self.model.value.lower()}))
        if self.mac:
            children.append(xml_element("mac", attributes={"address": self.mac}))
        if self.pci_address:
            children.append(self.pci_address.to_xml_element())

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
    def run(self, connection: Connection, domain_uuid: str) -> Generator[None, None, None]:
        with netlink_route() as sock:
            try:
                link = get_link(sock, self.identity())
                # Check if interface is UP by testing the IFF_UP flag
                if not (link.flags & InterfaceFlags.UP.value):
                    set_link_up(sock, index=link.index)
            except DeviceNotFound:
                # Interface doesn't exist, nothing to bring up
                pass
        yield

    def is_available_impl(self) -> bool:
        with netlink_route() as sock:
            try:
                get_link(sock, self.identity())
                return True
            except DeviceNotFound:
                return False

    def identity_impl(self) -> str:
        nic_attach = self.source
        if not nic_attach:
            with netlink_route() as sock:
                if default_route := get_default_route(sock):
                    assert default_route.oif_name is not None
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

        if self.mac:
            if not MAC_ADDRESS_RE.match(self.mac):
                verrors.append(
                    ('mac', 'MAC address must be a colon-separated hexadecimal value (e.g. `00:a0:99:7e:bb:8a`)')
                )
            elif self.mac.lower().startswith('ff'):
                verrors.append(
                    ('mac', 'MAC address must not start with `ff`')
                )
        return verrors
