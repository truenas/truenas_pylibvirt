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
        return parse_numeric_set(self.cpuset)


def parse_numeric_set(value):
    if value == '':
        return []

    cpus = {}
    parts = value.split(',')
    for part in parts:
        part = part.split('-')
        if len(part) == 1:
            cpu = int(part[0])
            cpus[cpu] = None
        elif len(part) == 2:
            start = int(part[0])
            end = int(part[1])
            if start >= end:
                raise ValueError(f'End of range has to greater that start: {start}-{end}')
            for cpu in range(start, end + 1):
                cpus[cpu] = None
        else:
            raise ValueError(f'Range has to be in format start-end: {part}')

    return list(cpus)
