"""Tests for storage device (Disk and RAW) XML generation."""
from __future__ import annotations

import pytest
from xml.etree import ElementTree as ET

from truenas_pylibvirt.device import DiskStorageDevice, RawStorageDevice, StorageDeviceType, StorageDeviceIoType


@pytest.mark.parametrize("path,type_,io_type,serial,expected_xml", [
    (
        "/dev/zvol/pool/boot_1",
        StorageDeviceType.AHCI,
        StorageDeviceIoType.THREADS,
        "test-serial",
        '<disk type="block" device="disk">'
        '<driver type="raw" cache="none" io="threads" discard="unmap" />'
        '<source dev="/dev/zvol/pool/boot_1" />'
        '<target bus="sata" dev="sda" />'
        '<serial>test-serial</serial>'
        '<boot order="1" />'
        '</disk>'
    ),
])
def test_disk_xml_generation(path, type_, io_type, serial, expected_xml, device_context, mock_device_delegate):
    """Test Disk storage device XML generation."""
    device = DiskStorageDevice(
        type_=type_,
        path=path,
        logical_sectorsize=None,
        physical_sectorsize=None,
        iotype=io_type,
        serial=serial,
        device_delegate=mock_device_delegate
    )

    xml_elements = device.xml(device_context)
    xml_str = ''.join(ET.tostring(elem, encoding='unicode') for elem in xml_elements).strip()

    assert xml_str == expected_xml


@pytest.mark.parametrize("path,type_,io_type,serial,logical,physical,expected_xml", [
    (
        "/mnt/tank/somefile",
        StorageDeviceType.AHCI,
        StorageDeviceIoType.THREADS,
        "test-serial",
        None,
        None,
        '<disk type="file" device="disk">'
        '<driver type="raw" cache="none" io="threads" discard="unmap" />'
        '<source file="/mnt/tank/somefile" />'
        '<target bus="sata" dev="sda" />'
        '<serial>test-serial</serial>'
        '<boot order="1" />'
        '</disk>'
    ),
    (
        "/mnt/tank/somefile",
        StorageDeviceType.AHCI,
        StorageDeviceIoType.THREADS,
        "test-serial",
        512,
        512,
        '<disk type="file" device="disk">'
        '<driver type="raw" cache="none" io="threads" discard="unmap" />'
        '<source file="/mnt/tank/somefile" />'
        '<target bus="sata" dev="sda" />'
        '<serial>test-serial</serial>'
        '<boot order="1" />'
        '<blockio physical_block_size="512" />'
        '</disk>'
    ),
])
def test_raw_xml_generation(
    path, type_, io_type, serial, logical, physical, expected_xml,
    device_context, mock_device_delegate
):
    """Test RAW storage device XML generation."""
    device = RawStorageDevice(
        type_=type_,
        path=path,
        logical_sectorsize=logical,
        physical_sectorsize=physical,
        iotype=io_type,
        serial=serial,
        device_delegate=mock_device_delegate
    )

    xml_elements = device.xml(device_context)
    xml_str = ''.join(ET.tostring(elem, encoding='unicode') for elem in xml_elements).strip()

    assert xml_str == expected_xml


def test_disk_identity(mock_device_delegate):
    """Test Disk device identity returns the path."""
    device = DiskStorageDevice(
        type_=StorageDeviceType.AHCI,
        path="/dev/zvol/pool/boot_1",
        logical_sectorsize=None,
        physical_sectorsize=None,
        iotype=StorageDeviceIoType.THREADS,
        serial="test-serial",
        device_delegate=mock_device_delegate
    )

    assert device.identity() == "/dev/zvol/pool/boot_1"


def test_raw_identity(mock_device_delegate):
    """Test RAW device identity returns the path."""
    device = RawStorageDevice(
        type_=StorageDeviceType.AHCI,
        path="/mnt/tank/somefile",
        logical_sectorsize=None,
        physical_sectorsize=None,
        iotype=StorageDeviceIoType.THREADS,
        serial="test-serial",
        device_delegate=mock_device_delegate
    )

    assert device.identity() == "/mnt/tank/somefile"
