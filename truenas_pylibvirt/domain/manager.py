import time
from xml.etree import ElementTree

from ..libvirtd.connection import Connection, DomainState
from ..error import Error, DomainDoesNotExistError
from .base.domain import BaseDomain


class DomainManager:
    def __init__(self, connection: Connection):
        self.connection = connection

    def start(self, domain: BaseDomain):
        xml = ElementTree.tostring(domain.xml_generator().generate()).decode()

        self.connection.define_domain(xml)

        libvirtd_domain = self.connection.get_domain(domain.configuration.uuid)
        if libvirtd_domain.create() < 0:
            raise Error(f"Failed to create domain {domain.configuration.name!r}")

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

        if self.connection.domain_state(libvirt_domain) != DomainState.SUSPENDED:
            raise Error(f"Domain {domain.configuration.name!r} is not suspended")

        libvirt_domain.resume()

    def delete(self, domain: BaseDomain):
        libvirt_domain = self._libvirt_domain(domain)
        if self.connection.domain_state(libvirt_domain) in [DomainState.RUNNING, DomainState.SUSPENDED]:
            self._destroy(libvirt_domain)
            # We would like to wait at least 7 seconds to have the vm complete its post vm actions which might require
            # interaction with its domain
            time.sleep(7)

        libvirt_domain.undefine()

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
