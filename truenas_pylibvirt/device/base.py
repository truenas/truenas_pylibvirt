from contextlib import contextmanager
from dataclasses import dataclass

from .counters import Counters


@dataclass
class DeviceXmlContext:
    counters: Counters


@dataclass(kw_only=True)
class Device:
    def xml(self, context: DeviceXmlContext):
        raise NotImplementedError()

    @contextmanager
    def run(self):
        yield
