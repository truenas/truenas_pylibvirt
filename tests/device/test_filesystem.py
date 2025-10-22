"""Tests for Filesystem device XML generation."""
from __future__ import annotations

import pytest
from xml.etree import ElementTree as ET

from truenas_pylibvirt.device import FilesystemDevice


@pytest.mark.parametrize("source,target,expected_xml", [
    (
        "/mnt/tank/shared",
        "/shared",
        '<filesystem type="mount">'
        '<source dir="/mnt/tank/shared" />'
        '<target dir="/shared" />'
        '</filesystem>'
    ),
])
def test_filesystem_xml_generation(source, target, expected_xml, device_context, mock_device_delegate):
    """Test Filesystem device XML generation."""
    device = FilesystemDevice(
        source=source,
        target=target,
        device_delegate=mock_device_delegate
    )
    xml_elements = device.xml(device_context)

    # Combine all XML elements into a single string
    xml_str = ''.join(ET.tostring(elem, encoding='unicode') for elem in xml_elements).strip()

    assert xml_str == expected_xml


def test_filesystem_identity(mock_device_delegate):
    """Test Filesystem device identity returns source:target."""
    device = FilesystemDevice(
        source="/mnt/tank/shared",
        target="/shared",
        device_delegate=mock_device_delegate
    )
    assert device.identity() == "/mnt/tank/shared:/shared"


def test_filesystem_validation(mock_device_delegate):
    """Test Filesystem device validation."""
    device = FilesystemDevice(
        source="/mnt/tank/shared",
        target="/shared",
        device_delegate=mock_device_delegate
    )

    # Filesystem devices have validation - mainly delegate checks
    errors = device.validate()
    assert isinstance(errors, list)
