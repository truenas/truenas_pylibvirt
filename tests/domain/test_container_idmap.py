"""Tests for container idmap configuration and XML generation."""

from __future__ import annotations

import sys
import types
from unittest.mock import Mock

import pytest

# Stub the libvirt module so the library's device imports don't blow up in
# environments without the python3-libvirt system package installed.
sys.modules.setdefault("libvirt", types.ModuleType("libvirt"))

from truenas_pylibvirt.domain.container.configuration import (  # noqa: E402
    ContainerIdmapConfiguration,
    ContainerIdmapConfigurationItem,
)
from truenas_pylibvirt.domain.container.xml import ContainerDomainXmlGenerator  # noqa: E402


def _item(start: int, target: int, count: int) -> ContainerIdmapConfigurationItem:
    return ContainerIdmapConfigurationItem(start=start, target=target, count=count)


def test_single_entry_idmap_is_valid():
    cfg = ContainerIdmapConfiguration(
        uid=[_item(0, 2147000001, 65536)],
        gid=[_item(0, 2147000001, 65536)],
    )
    assert cfg.uid[0].target == 2147000001


def test_multi_entry_idmap_with_passthrough_segment_is_valid():
    # Container 0..567 -> host 2147000001..2147000568, container 568 -> host 568,
    # container 569..65535 -> host 2147000570..2147065536
    cfg = ContainerIdmapConfiguration(
        uid=[
            _item(0, 2147000001, 568),
            _item(568, 568, 1),
            _item(569, 2147000570, 64967),
        ],
        gid=[
            _item(0, 2147000001, 568),
            _item(568, 568, 1),
            _item(569, 2147000570, 64967),
        ],
    )
    assert len(cfg.uid) == 3


def test_empty_uid_list_rejected():
    with pytest.raises(ValueError, match="At least one uid idmap entry is required"):
        ContainerIdmapConfiguration(uid=[], gid=[_item(0, 1, 1)])


def test_empty_gid_list_rejected():
    with pytest.raises(ValueError, match="At least one gid idmap entry is required"):
        ContainerIdmapConfiguration(uid=[_item(0, 1, 1)], gid=[])


def test_zero_count_rejected():
    with pytest.raises(ValueError, match="count must be positive"):
        ContainerIdmapConfiguration(uid=[_item(0, 1, 0)], gid=[_item(0, 1, 1)])


def test_negative_start_rejected():
    with pytest.raises(ValueError, match="start/target must be non-negative"):
        ContainerIdmapConfiguration(uid=[_item(-1, 1, 1)], gid=[_item(0, 1, 1)])


def test_negative_target_rejected():
    with pytest.raises(ValueError, match="start/target must be non-negative"):
        ContainerIdmapConfiguration(uid=[_item(0, -1, 1)], gid=[_item(0, 1, 1)])


def test_overlapping_container_ranges_rejected():
    with pytest.raises(ValueError, match="container-side ranges overlap"):
        ContainerIdmapConfiguration(
            uid=[_item(0, 1000, 100), _item(50, 2000, 100)],
            gid=[_item(0, 1, 1)],
        )


def test_overlapping_host_ranges_rejected():
    with pytest.raises(ValueError, match="host-side ranges overlap"):
        ContainerIdmapConfiguration(
            uid=[_item(0, 1000, 100), _item(200, 1050, 100)],
            gid=[_item(0, 1, 1)],
        )


def test_xml_emits_one_element_per_item():
    cfg = ContainerIdmapConfiguration(
        uid=[
            _item(0, 2147000001, 568),
            _item(568, 568, 1),
            _item(569, 2147000570, 64967),
        ],
        gid=[
            _item(0, 2147000001, 568),
            _item(568, 568, 1),
            _item(569, 2147000570, 64967),
        ],
    )

    mock_domain = Mock()
    mock_domain.configuration.idmap = cfg

    generator = ContainerDomainXmlGenerator.__new__(ContainerDomainXmlGenerator)
    generator.domain = mock_domain

    misc = generator._misc_xml()
    assert len(misc) == 1
    idmap_el = misc[0]
    assert idmap_el.tag == "idmap"

    uid_children = idmap_el.findall("uid")
    gid_children = idmap_el.findall("gid")
    assert len(uid_children) == 3
    assert len(gid_children) == 3

    apps_uid = next(u for u in uid_children if u.get("start") == "568")
    assert apps_uid.get("target") == "568"
    assert apps_uid.get("count") == "1"

    base_uid = next(u for u in uid_children if u.get("start") == "0")
    assert base_uid.get("target") == "2147000001"
    assert base_uid.get("count") == "568"


def test_xml_omits_idmap_when_configuration_is_none():
    mock_domain = Mock()
    mock_domain.configuration.idmap = None

    generator = ContainerDomainXmlGenerator.__new__(ContainerDomainXmlGenerator)
    generator.domain = mock_domain

    misc = generator._misc_xml()
    assert misc == []


def test_x_mount_idmap_spec_is_space_separated():
    from truenas_pylibvirt.domain.container.domain import ContainerDomain

    domain = ContainerDomain.__new__(ContainerDomain)
    items = [
        _item(0, 2147000001, 568),
        _item(568, 568, 1),
        _item(569, 2147000570, 64967),
    ]
    spec = domain._x_mount_idmap("u", items)
    assert spec == "u:0:2147000001:568 u:568:568:1 u:569:2147000570:64967"

    spec_g = domain._x_mount_idmap("g", items[:1])
    assert spec_g == "g:0:2147000001:568"
