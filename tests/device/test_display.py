"""Tests for Display device XML generation."""
from __future__ import annotations

import pytest
from xml.etree import ElementTree as ET

from truenas_pylibvirt.device import DisplayDevice, DisplayDeviceType


@pytest.mark.parametrize("type_,resolution,port,web_port,bind,password,web,wait,expected_xml", [
    (
        DisplayDeviceType.SPICE,
        "1024x768",
        5912,
        5913,
        "0.0.0.0",
        "",
        True,
        False,
        '<graphics type="spice" port="5912">'
        '<listen type="address" address="0.0.0.0" />'
        '</graphics>'
        '<controller type="usb" model="nec-xhci" />'
        '<input type="tablet" bus="usb" />'
        '<video>'
        '<model type="qxl" vgamem="65536" ram="131072" vram="65536">'
        '<resolution x="1024" y="768" />'
        '</model>'
        '</video>'
    ),
])
def test_display_xml_generation(
    type_, resolution, port, web_port, bind, password, web, wait,
    expected_xml, device_context, mock_device_delegate
):
    """Test Display device XML generation."""
    device = DisplayDevice(
        type_=type_,
        resolution=resolution,
        port=port,
        web_port=web_port,
        bind=bind,
        password=password,
        web=web,
        wait=wait,
        device_delegate=mock_device_delegate
    )

    xml_elements = device.xml(device_context)
    xml_str = ''.join(ET.tostring(elem, encoding='unicode') for elem in xml_elements).strip()

    assert xml_str == expected_xml


def test_display_identity(mock_device_delegate):
    """Test Display device identity."""
    device = DisplayDevice(
        type_=DisplayDeviceType.SPICE,
        resolution="1024x768",
        port=5912,
        web_port=5913,
        bind="0.0.0.0",
        password="",
        web=True,
        wait=False,
        device_delegate=mock_device_delegate
    )

    # Display devices use bind:port for identity
    identity = device.identity()
    assert identity == "0.0.0.0:5912"
