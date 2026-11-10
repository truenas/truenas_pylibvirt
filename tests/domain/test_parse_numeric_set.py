import pytest

from truenas_pylibvirt.domain.base.configuration import parse_numeric_set


@pytest.mark.parametrize("value,expected", [
    ("", []),
    ("0-0", [0]),
    ("3,1,1-2", [3, 1, 2]),
    (" 0 , 2 - 3 ", [0, 2, 3]),
])
def test_parse_numeric_set_valid(value, expected):
    assert parse_numeric_set(value) == expected


@pytest.mark.parametrize("value", ["3-1", "1-2-3", "+1", "1_0", "٣", "1-", "1,,2", " "])
def test_parse_numeric_set_invalid(value):
    with pytest.raises(ValueError):
        parse_numeric_set(value)
