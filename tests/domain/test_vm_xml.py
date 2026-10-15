"""Tests for VM XML generation."""
from __future__ import annotations

from unittest.mock import Mock
from xml.etree import ElementTree as ET

import pytest

from truenas_pylibvirt.device import DisplayDevice, DisplayDeviceType
from truenas_pylibvirt.domain.vm.configuration import VmVideoModel
from truenas_pylibvirt.domain.vm.xml import VmDomainXmlGenerator


def _generator(*, ensure_display_device: bool = False, devices: list | None = None) -> VmDomainXmlGenerator:
    config = Mock()
    config.trusted_platform_module = False
    config.tpm_path = '/tmp/tpm'
    config.min_memory = None
    config.ensure_display_device = ensure_display_device
    config.devices = devices if devices is not None else []
    domain = Mock()
    domain.configuration = config
    gen = VmDomainXmlGenerator.__new__(VmDomainXmlGenerator)
    gen.domain = domain
    return gen


def _display_device(type_, resolution, port):
    return DisplayDevice(
        type_=type_,
        resolution=resolution,
        port=port,
        web_port=port + 1,
        bind="0.0.0.0",
        wait=False,
        password="secret",
        web=False,
        device_delegate=Mock(),
    )


@pytest.mark.parametrize("video_model,ensure_display_device,displays,expected_xml", [
    (VmVideoModel.VGA, False, [], ""),
    (VmVideoModel.VGA, True, [], '<video><model type="vga" /></video>'),
    (
        VmVideoModel.QXL,
        False,
        [(DisplayDeviceType.VNC, "1280x720", 5900), (DisplayDeviceType.SPICE, "1920x1080", 5910)],
        '<video>'
        '<model type="qxl" vgamem="65536" ram="131072" vram="65536">'
        '<resolution x="1280" y="720" />'
        '</model>'
        '</video>',
    ),
])
def test_video_xml(video_model, ensure_display_device, displays, expected_xml):
    gen = _generator(
        ensure_display_device=ensure_display_device,
        devices=[_display_device(*display) for display in displays],
    )
    gen.domain.configuration.video_model = video_model
    videos = [d for d in gen._devices_xml_children() if d.tag == "video"]
    assert ''.join(ET.tostring(video, encoding='unicode') for video in videos) == expected_xml
