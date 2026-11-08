from __future__ import annotations

from dataclasses import dataclass
import enum

from ...device.base import Device


class Time(enum.Enum):
    LOCAL = "LOCAL"
    UTC = "UTC"


@dataclass(kw_only=True)
class BaseDomainConfiguration:
    uuid: str
    name: str
    description: str
    vcpus: int | None
    cores: int | None
    threads: int | None
    cpuset: str | None
    memory: int | None
    time: Time
    shutdown_timeout: int
    devices: list[Device]

    @property
    def cpuset_list(self) -> list[int]:
        return parse_numeric_set(self.cpuset or '')


def parse_numeric_set(value: str) -> list[int]:
    if value == '':
        return []

    cpus: dict[int, None] = {}
    for part in value.split(','):
        pieces = part.split('-')
        if len(pieces) > 2:
            raise ValueError(f'Range has to be in format start-end: {part.strip()!r}')

        start, end = _parse_number(pieces[0]), _parse_number(pieces[-1])
        if start > end:
            raise ValueError(f'End of range has to be greater than or equal to start: {part.strip()!r}')

        cpus.update(dict.fromkeys(range(start, end + 1)))

    return list(cpus)


def _parse_number(value: str) -> int:
    stripped = value.strip()
    if not stripped:
        raise ValueError('Empty elements are not allowed')
    if not (stripped.isascii() and stripped.isdigit()):
        raise ValueError(f'{stripped!r} must consist of digits 0-9 only')
    return int(stripped)
