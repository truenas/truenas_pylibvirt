"""Tests for BaseDomainConfiguration."""
from __future__ import annotations

from typing import Any

import pytest

from truenas_pylibvirt.domain.base.configuration import BaseDomainConfiguration, Time


def _config(**overrides: Any) -> BaseDomainConfiguration:
    defaults: dict[str, Any] = dict(
        uuid="2f9a4a5f-0f7f-4d1e-9c3a-7c9f3b5d2e11",
        name="test",
        description="",
        vcpus=1,
        cores=1,
        threads=1,
        cpuset=None,
        memory=1024,
        time=Time.UTC,
        shutdown_timeout=90,
        devices=[],
    )
    return BaseDomainConfiguration(**(defaults | overrides))


@pytest.mark.parametrize("value,expected", [
    ("LOCAL", Time.LOCAL),
    ("UTC", Time.UTC),
    (Time.LOCAL, Time.LOCAL),
    (Time.UTC, Time.UTC),
])
def test_time_is_normalised_to_the_enum(value, expected):
    """A caller unpacking an untyped dict may supply the string form; it must not survive."""
    assert _config(time=value).time is expected


def test_invalid_time_raises():
    with pytest.raises(ValueError):
        _config(time="EASTERN")
