from __future__ import annotations

from dataclasses import dataclass
import enum
import functools
import logging
import os
import threading
from typing import Any, Callable, TYPE_CHECKING

import libvirt
import libvirt_qemu

from ..error import Error, GuestAgentError, is_no_domain_error

if TYPE_CHECKING:
    from .connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


@functools.cache
def kvm_supported() -> bool:
    return os.path.exists('/dev/kvm')


class DomainState(enum.Enum):
    NOSTATE = "NOSTATE"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    PAUSED = "PAUSED"
    SHUTDOWN = "SHUTDOWN"
    SHUTOFF = "SHUTOFF"
    CRASHED = "CRASHED"
    PMSUSPENDED = "PMSUSPENDED"
    UPDATING_CONFIGURATION = "UPDATING_CONFIGURATION"
    UNKNOWN = "UNKNOWN"


class VirDomainEvent(enum.Enum):
    DEFINED = "DEFINED"
    UNDEFINED = "UNDEFINED"
    STARTED = "STARTED"
    SUSPENDED = "SUSPENDED"
    RESUMED = "RESUMED"
    STOPPED = "STOPPED"
    SHUTDOWN = "SHUTDOWN"
    PMSUSPENDED = "PMSUSPENDED"
    CRASHED = "CRASHED"
    UNKNOWN = "UNKNOWN"


class DomainEventType(enum.Enum):
    ADDED = "ADDED"
    CHANGED = "CHANGED"


@dataclass
class DomainEvent:
    event: VirDomainEvent
    uuid: str


DomainEventCallback = Callable[[DomainEvent], None]


class Connection:
    def __init__(self, manager: ConnectionManager, uri: str):
        self.manager = manager
        self.uri = uri
        self._connection: Any = None
        self._callback_id: int | None = None
        self._connection_lock = threading.Lock()
        self._domain_event_callbacks: list[DomainEventCallback] = []

    @property
    def connection(self) -> Any:
        # Serialize check+reconnect so concurrent callers don't open (and leak)
        # multiple connections.
        with self._connection_lock:
            if self._connection is not None and self._connection_is_alive(self._connection):
                return self._connection

            self._open()
            return self._connection

    @staticmethod
    def _connection_is_alive(connection: Any) -> bool:
        # NAS-109072: a dead connection raises here instead of returning falsy.
        try:
            return bool(connection.isAlive()) and isinstance(connection.listAllDomains(), list)
        except libvirt.libvirtError:
            return False

    def register_domain_event_callback(self, callback: DomainEventCallback) -> None:
        self._domain_event_callbacks.append(callback)

    def list_domains(self) -> list[Any]:
        return list(self.connection.listAllDomains())

    def define_domain(self, xml: str) -> None:
        if not self.connection.defineXML(xml):
            raise Error("Failed to define a domain from an XML definition")

    def get_domain(self, uuid: str) -> Any:
        try:
            return self.connection.lookupByName(uuid)
        except libvirt.libvirtError as e:
            if is_no_domain_error(e):
                return None

            raise

    def domain_memory_usage(self, domain: Any) -> int:
        return int(domain.memoryStats().get("actual", 0) * 1024)

    def guest_agent_command(self, domain: Any, command: str, timeout: int = 30) -> str:
        """Send a QEMU guest agent command and return the raw JSON response string.

        Raises GuestAgentError if the guest agent is unavailable or times out.
        """
        try:
            return str(libvirt_qemu.qemuAgentCommand(domain, command, timeout, 0))
        except libvirt.libvirtError as e:
            raise GuestAgentError(f"Guest agent command failed: {e}")

    def domain_state(self, domain: Any) -> DomainState:
        return {
            libvirt.VIR_DOMAIN_NOSTATE: DomainState.NOSTATE,
            libvirt.VIR_DOMAIN_RUNNING: DomainState.RUNNING,
            libvirt.VIR_DOMAIN_BLOCKED: DomainState.BLOCKED,
            libvirt.VIR_DOMAIN_PAUSED: DomainState.PAUSED,
            libvirt.VIR_DOMAIN_SHUTDOWN: DomainState.SHUTDOWN,
            libvirt.VIR_DOMAIN_SHUTOFF: DomainState.SHUTOFF,
            libvirt.VIR_DOMAIN_CRASHED: DomainState.CRASHED,
            libvirt.VIR_DOMAIN_PMSUSPENDED: DomainState.PMSUSPENDED,
        }[domain.state()[0]]

    def domain_event(self, event: int) -> VirDomainEvent:
        return {
            libvirt.VIR_DOMAIN_EVENT_DEFINED: VirDomainEvent.DEFINED,
            libvirt.VIR_DOMAIN_EVENT_UNDEFINED: VirDomainEvent.UNDEFINED,
            libvirt.VIR_DOMAIN_EVENT_STARTED: VirDomainEvent.STARTED,
            libvirt.VIR_DOMAIN_EVENT_SUSPENDED: VirDomainEvent.SUSPENDED,
            libvirt.VIR_DOMAIN_EVENT_RESUMED: VirDomainEvent.RESUMED,
            libvirt.VIR_DOMAIN_EVENT_STOPPED: VirDomainEvent.STOPPED,
            libvirt.VIR_DOMAIN_EVENT_SHUTDOWN: VirDomainEvent.SHUTDOWN,
            libvirt.VIR_DOMAIN_EVENT_PMSUSPENDED: VirDomainEvent.PMSUSPENDED,
            libvirt.VIR_DOMAIN_EVENT_CRASHED: VirDomainEvent.CRASHED
        }.get(event, VirDomainEvent.UNKNOWN)

    def _open(self) -> None:
        # Release the connection being replaced so it isn't leaked, but do not close it:
        # `connection` hands out the raw handle and drops the lock before its caller makes
        # an RPC, so another thread can still be inside a call on this one. Closing frees
        # the connection regardless of who is mid-call, taking it out from under that
        # thread. Deregistering releases the reference that would otherwise outlive us, so
        # the handle is disposed once its last user lets go of it.
        if self._connection is not None:
            old, old_callback_id = self._connection, self._callback_id
            self._connection, self._callback_id = None, None
            self._discard(old, old_callback_id, close=False)

        # A libvirtd that accepts the connection but never completes the handshake blocks
        # here for as long as it stays wedged, with `_connection_lock` held.
        connection = self.manager.open(self.uri)

        callback_id: int | None = None
        try:
            callback_id = connection.domainEventRegisterAny(
                None, libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE, self._libvirt_event_callback, None
            )
            connection.setKeepAlive(5, 3)
        except Exception:
            # Nothing records this handle yet, so no later code path would tear it down, and
            # no other thread can be using it either -- so unlike the reconnect path above it
            # is safe (and necessary) to close it here. Broad, because what this has to catch
            # is "setup did not finish", not one library's idea of how it failed: registration
            # can already have pinned the handle by the time the failure happens.
            try:
                self._discard(connection, callback_id)
            except libvirt.libvirtError:
                logger.debug("Failed to discard libvirt connection for %s after setup error", self.uri, exc_info=True)
            raise

        self._connection = connection
        self._callback_id = callback_id

    def _close(self) -> None:
        # Deliberately not `self.connection`: the property would open a handle -- starting
        # libvirtd along the way -- purely so that it could be closed again.
        with self._connection_lock:
            if self._connection is None:
                return

            old, callback_id = self._connection, self._callback_id
            self._connection, self._callback_id = None, None

        try:
            self._discard(old, callback_id)
        except libvirt.libvirtError as e:
            raise Error(f"Failed to close libvirt connection: {e}")

    def _discard(self, connection: Any, callback_id: int | None, close: bool = True) -> None:
        # Registering an event callback makes libvirt hold a reference on the handle that only
        # deregistering releases, so a handle that is closed but not deregistered stays open --
        # and keeps dispatching domain events -- for the life of the process. Deregistering is
        # what actually lets the handle go, which is why the reconnect path can rely on it alone.
        #
        # It is best-effort: the RPC fails once the socket is gone, but libvirt releases the
        # callback locally before sending it, so the reference is dropped either way. Broad,
        # because nothing raised while giving the callback back may stop the handle being
        # released -- which on the reconnect path is all that happens here.
        if callback_id is not None:
            try:
                connection.domainEventDeregisterAny(callback_id)
            except Exception:
                logger.debug("Failed to deregister libvirt domain events for %s", self.uri)

        if close:
            connection.close()

    def _libvirt_event_callback(self, conn: Any, dom: Any, event: int, detail: int, opaque: Any) -> None:
        domain_event = DomainEvent(uuid=dom.name(), event=self.domain_event(event))
        for callback in self._domain_event_callbacks:
            try:
                callback(domain_event)
            except Exception:
                logger.error("Unhandled exception in domain event callback %r", callback, exc_info=True)
