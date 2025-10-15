from __future__ import annotations

import enum
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..xml import xml_element
from .base import Device, DeviceXmlContext


if TYPE_CHECKING:
    from ..libvirtd.connection import Connection


class DisplayDeviceType(enum.Enum):
    SPICE = "SPICE"
    VNC = "VNC"


@dataclass(kw_only=True)
class DisplayDevice(Device):

    type_: DisplayDeviceType
    resolution: str
    port: int | None
    web_port: int | None
    bind: str
    wait: bool
    password: str
    web: bool = True

    def xml(self, context: DeviceXmlContext):
        # FIXME: Resolution is not respected when we have more then 1 display device as we are not able to bind
        #  video element to a graphic element
        return [
            xml_element(
                "graphics",
                attributes={
                    "type": self.type_.value.lower(),
                    "port": str(self.port),
                    **({"passwd": self.password} if self.password else {})
                },
                children=[
                    xml_element("listen", attributes={"type": "address", "address": self.bind}),
                ],
            ),
            xml_element(
                "controller",
                attributes={"type": "usb", "model": "nec-xhci"},
            ),
            xml_element(
                "input",
                attributes={"type": "tablet", "bus": "usb"}
            ),
            xml_element(
                "video",
                children=[
                    xml_element(
                        "model",
                        attributes={
                            "type": "qxl",
                            # We have seen that on higher resolutions, the default values libvirt sets
                            # for `vgamem/ram/vram` might not be sufficient and keeping that in mind,
                            # changes have been added to have reasonable defaults for these attrs so
                            # we support all the resolutions out of the box.
                            "vgamem": str(64 * 1024),
                            "ram": str(128 * 1024),
                            "vram": str(64 * 1024),
                        },
                        children=[
                            xml_element(
                                "resolution",
                                attributes={"x": self.resolution.split("x")[0], "y": self.resolution.split("x")[-1]},
                            )
                        ],
                    ),
                ],
            )
        ]

    @contextmanager
    def run(self, connection: Connection, domain_uuid: str):
        process = None
        if self.type_ == DisplayDeviceType.SPICE:
            web_bind = f":{self.web_port}" if self.bind == "0.0.0.0" else f"{self.bind}:{self.web_port}"
            server_addr = f"{self.bind}:{self.port}"
            process = subprocess.Popen(
                ["websockify", "--web", "/usr/share/spice-html5/", "--wrap-mode=ignore", web_bind, server_addr],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        try:
            yield
        finally:
            if process:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

    def identity_impl(self) -> str:
        return f"{self.bind}:{self.port}"

    def is_available_impl(self) -> bool:
        return True

    def validate_impl(self) -> list[tuple[str, str]]:
        verrors = []
        if not self.password or not self.password.strip():
            verrors.append(('password', 'Password is required for display devices'))

        if self.type_ == DisplayDeviceType.VNC:
            if self.web:
                verrors.append(
                    ('web', 'Web access is not supported for VNC display devices, please use SPICE instead')
                )
            if self.password and len(self.password) > 8:
                # libvirt error otherwise i.e
                # libvirt.libvirtError: unsupported configuration: VNC password is 11 characters long, only 8 permitted
                verrors.append(
                    ('password', 'Password for VNC display devices must be 8 characters or less')
                )
        elif self.type_ == DisplayDeviceType.SPICE:
            if self.port == self.web_port:
                verrors.append(
                    ('port', 'Spice server port must not be same as web port')
                )
        return verrors
