from contextlib import ExitStack
import logging
import threading
import time
from xml.etree import ElementTree

from ..error import Error, DomainDoesNotExistError
from ..libvirtd.connection import Connection, DomainEvent, DomainState, VirDomainEvent
from .base.domain import BaseDomain
from .start_validator import StartValidator, StartValidationContext

logger = logging.getLogger(__name__)

STOPPED_STATES = [DomainState.SHUTDOWN, DomainState.SHUTOFF, DomainState.CRASHED]
STOPPED_EVENTS = [VirDomainEvent.STOPPED, VirDomainEvent.SHUTDOWN, VirDomainEvent.UNDEFINED]


class StartedDomain:
    def __init__(self, domain: BaseDomain, connection: Connection):
        self.connection = connection
        self.domain = domain
        self.exit_stack = ExitStack()

        self.exit_stack.enter_context(self.domain.device_manager.start(connection))
        self.context = self.exit_stack.enter_context(self.domain.run())

    def cleanup(self):
        self.exit_stack.close()


class DomainManager:
    def __init__(self, connection: Connection):
        self.connection = connection
        self.started_domains: dict[str, StartedDomain] = {}
        self.started_domains_lock = threading.Lock()
        self.start_validator = StartValidator()

        self.connection.register_domain_event_callback(self._domain_event_callback)

    def start(self, domain: BaseDomain):
        with self.started_domains_lock:
            if started_domain := self.started_domains.pop(domain.configuration.uuid, None):
                if libvirt_domain := self.connection.get_domain(domain.configuration.uuid):
                    domain_state = self.connection.domain_state(libvirt_domain)
                    if domain_state in STOPPED_STATES:
                        logger.info(
                            f"Requested to start domain {domain.configuration.name!r}. It is present in "
                            f"`started_domains`, but its state is {domain_state!r}. This should not happen. "
                            "Performing clean-up routing."
                        )
                        started_domain.cleanup()
                    else:
                        raise Error(f"Domain {domain.configuration.name!r} is already started ({domain_state!r}).")

            validation_context = StartValidationContext(
                connection=self.connection,
                domain_uuid=domain.configuration.uuid
            )

            errors = self.start_validator.validate(domain.device_manager.devices, validation_context)
            if errors:
                error_msg = "\n".join([f"{field}: {error}" for field, error in errors])
                raise Error(f"Cannot start domain {domain.configuration.name!r}:\n{error_msg}")

            started_domain = StartedDomain(domain, self.connection)
            created = False
            try:
                xml = ElementTree.tostring(domain.xml_generator(started_domain.context).generate()).decode()

                self.connection.define_domain(xml)

                libvirtd_domain = self.connection.get_domain(domain.configuration.uuid)

                if libvirtd_domain.create() < 0:
                    raise Error(f"Failed to create domain {domain.configuration.name!r}")

                created = True
            finally:
                if created:
                    self.started_domains[domain.configuration.uuid] = started_domain
                else:
                    started_domain.cleanup()

    def shutdown(self, domain: BaseDomain, shutdown_timeout: int | None = None):
        libvirt_domain = self._libvirt_domain_for_stop(domain)

        shutdown_timeout = shutdown_timeout or domain.configuration.shutdown_timeout
        # We wait for timeout seconds before initiating post stop activities for the vm
        # This is done because the shutdown call above is non-blocking
        while shutdown_timeout > 0 and self.connection.domain_state(libvirt_domain) == DomainState.RUNNING:
            try:
                # Retry shutting down as sometimes LXC driver ignores this request
                libvirt_domain.shutdown()
            except Exception:
                pass

            shutdown_timeout -= 1
            time.sleep(1)

    def destroy(self, domain: BaseDomain):
        libvirt_domain = self._libvirt_domain_for_stop(domain)
        self._destroy(libvirt_domain)

    def _destroy(self, libvirt_domain):
        try:
            libvirt_domain.destroy()
        except Exception:
            if self.connection.domain_state(libvirt_domain) == DomainState.SHUTOFF:
                # Sometimes `libvirt.libvirtError: Failed to read /sys/fs/cgroup/machine.slice/machine-lxc\x2d63139\x2d
                # c39e9acf\x2d517a\x2d4105\x2d8c76\x2df2fcd666011d.scope/libvirt/cgroup.threads: No such device` occurs.
                # The domain is really shutoff, so we don't care.
                return

            raise

    def suspend(self, domain: BaseDomain):
        libvirt_domain = self._libvirt_domain_for_stop(domain)
        libvirt_domain.suspend()

    def resume(self, domain: BaseDomain):
        libvirt_domain = self._libvirt_domain(domain)

        if self.connection.domain_state(libvirt_domain) != DomainState.PAUSED:
            raise Error(f"Domain {domain.configuration.name!r} is not suspended")

        libvirt_domain.resume()

    def delete(self, domain: BaseDomain):
        libvirt_domain = self._libvirt_domain(domain)
        if self.connection.domain_state(libvirt_domain) in [DomainState.RUNNING, DomainState.PAUSED]:
            self._destroy(libvirt_domain)
            # We would like to wait at least 7 seconds to have the vm complete its post vm actions which might require
            # interaction with its domain
            time.sleep(7)

        domain.undefine(libvirt_domain)

    def _libvirt_domain(self, domain: BaseDomain):
        libvirt_domain = self.connection.get_domain(domain.configuration.uuid)
        if libvirt_domain is None:
            raise DomainDoesNotExistError(f"Domain {domain.configuration.name!r} does not exist")

        return libvirt_domain

    def _libvirt_domain_for_stop(self, domain: BaseDomain):
        libvirt_domain = self._libvirt_domain(domain)

        if not libvirt_domain.isActive():
            raise Error(f"Domain {domain.configuration.name!r} is not active")

        return libvirt_domain

    def _domain_event_callback(self, event: DomainEvent):
        libvirt_domain = self.connection.get_domain(event.uuid)
        if libvirt_domain is None:
            return

        if event.event in STOPPED_EVENTS:
            with self.started_domains_lock:
                if started_domain := self.started_domains.pop(event.uuid, None):
                    started_domain.cleanup()
