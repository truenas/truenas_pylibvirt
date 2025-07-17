from dataclasses import dataclass
import enum
import functools
import logging
import os
from typing import Callable, TYPE_CHECKING

import libvirt

from ..error import Error

if TYPE_CHECKING:
    from .connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


@functools.cache
def kvm_supported():
    return os.path.exists('/dev/kvm')


class DomainState(enum.Enum):
    NOSTATE = "NOSTATE"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    SUSPENDED = "SUSPENDED"
    SHUTDOWN = "SHUTDOWN"
    SHUTOFF = "SHUTOFF"
    CRASHED = "CRASHED"
    PMSUSPENDED = "PMSUSPENDED"
    UPDATING_CONFIGURATION = "UPDATING_CONFIGURATION"
    UNKNOWN = "UNKNOWN"


class DomainEventType(enum.Enum):
    ADDED = "ADDED"
    CHANGED = "CHANGED"


@dataclass
class DomainEvent:
    uuid: str


DomainEventCallback = Callable[[DomainEvent], None]


class Connection:
    def __init__(self, manager: "ConnectionManager", uri: str):
        self.manager = manager
        self.uri = uri
        self._connection = None
        self._domain_event_callbacks: list[DomainEventCallback] = []

    @property
    def connection(self):
        # We see isAlive call failed for a user in NAS-109072, it would be better
        # if we handle this to ensure that system recognises libvirt connection
        # is no longer active and a new one should be initiated.
        if (
            self._connection and
            self._connection.isAlive() and
            isinstance(self._connection.listAllDomains(), list)
        ):
            return self._connection

        self._open()
        return self._connection

    def register_domain_event_callback(self, callback: DomainEventCallback):
        self._domain_event_callbacks.append(callback)

    def list_domains(self):
        return self.connection.listAllDomains()

    def define_domain(self, xml: str):
        if not self.connection.defineXML(xml):
            raise Error("Failed to define a domain from an XML definition")

    def get_domain(self, uuid: str):
        try:
            return self.connection.lookupByName(uuid)
        except libvirt.libvirtError as e:
            if e.err[0] == libvirt.VIR_ERR_NO_DOMAIN:
                return None

            raise

    def domain_memory_usage(self, domain) -> int:
        return domain.memoryStats().get("actual", 0) * 1024

    def domain_state(self, domain) -> DomainState:
        return {
            libvirt.VIR_DOMAIN_NOSTATE: DomainState.NOSTATE,
            libvirt.VIR_DOMAIN_RUNNING: DomainState.RUNNING,
            libvirt.VIR_DOMAIN_BLOCKED: DomainState.BLOCKED,
            libvirt.VIR_DOMAIN_PAUSED: DomainState.SUSPENDED,
            libvirt.VIR_DOMAIN_SHUTDOWN: DomainState.SHUTDOWN,
            libvirt.VIR_DOMAIN_SHUTOFF: DomainState.SHUTOFF,
            libvirt.VIR_DOMAIN_CRASHED: DomainState.CRASHED,
            libvirt.VIR_DOMAIN_PMSUSPENDED: DomainState.PMSUSPENDED,
        }[domain.state()[0]]

    def _open(self):
        connection = self.manager.open(self.uri)

        connection.domainEventRegister(self._libvirt_event_callback, None)
        connection.setKeepAlive(5, 3)

        self._connection = connection

    def _close(self):
        try:
            self.connection.close()
        except libvirt.libvirtError as e:
            raise Error(f"Failed to close libvirt connection: {e}")

        self._connection = None

    def _libvirt_event_callback(self, conn, dom, event, detail, opaque):
        event = DomainEvent(dom.name())
        for callback in self._domain_event_callbacks:
            try:
                callback(event)
            except Exception:
                logger.error("Unhandled exception in domain event callback %r", callback, exc_info=True)
