from contextlib import contextmanager
from dataclasses import dataclass

from .counters import Counters


@dataclass
class DeviceXmlContext:
    counters: Counters


class Device:
    def xml(self, context: DeviceXmlContext):
        raise NotImplementedError()

    @contextmanager
    def run(self):
        yield
