"""Tests for CDROM device XML generation."""
from __future__ import annotations

import pytest
from xml.etree import ElementTree as ET

from truenas_pylibvirt.device import CDROMDevice


@pytest.mark.parametrize("path,expected_xml", [
    (
        "/mnt/tank/disk.iso",
        '<disk type="file" device="cdrom">'
        '<driver type="raw" />'
        '<source file="/mnt/tank/disk.iso" />'
        '<target dev="sda" bus="sata" />'
        '<boot order="1" /></disk>'
    ),
])
def test_cdrom_xml_generation(path, expected_xml, device_context, mock_device_delegate):
    """Test CDROM device XML generation."""
    device = CDROMDevice(path=path, device_delegate=mock_device_delegate)
    xml_elements = device.xml(device_context)

    # Combine all XML elements into a single string
    xml_str = ''.join(ET.tostring(elem, encoding='unicode') for elem in xml_elements).strip()

    assert xml_str == expected_xml


def test_cdrom_identity(mock_device_delegate):
    """Test CDROM device identity returns the path."""
    device = CDROMDevice(path="/mnt/tank/disk.iso", device_delegate=mock_device_delegate)
    assert device.identity() == "/mnt/tank/disk.iso"


def test_cdrom_validation(mock_device_delegate):
    """Test CDROM device validation."""
    device = CDROMDevice(path="/mnt/tank/disk.iso", device_delegate=mock_device_delegate)

    # CDROM devices have minimal validation - mainly delegate checks
    errors = device.validate()
    assert isinstance(errors, list)
