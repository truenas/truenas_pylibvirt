from contextlib import contextmanager
import enum
import subprocess

from ..xml import xml_element
from .base import Device, DeviceXmlContext


class DisplayDeviceType(enum.Enum):
    SPLICE = "SPLICE"


class DisplayDevice(Device):
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
                    "type": "spice",
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
                        attributes={"type": "qxl"},
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
    def run(self):
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
            process.terminate()
