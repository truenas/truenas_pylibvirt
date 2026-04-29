from .manager import DomainManager
from ..libvirtd.connection_manager import ConnectionManager


# Libvirt connection URIs used by middleware + any sibling tooling that
# needs to reach the TrueNAS-owned libvirtd socket. Exported via the
# top-level package so callers can reference a single source of truth.
DEFAULT_CONTAINERS_URI = "lxc:///system?socket=/run/truenas_libvirt/libvirt-sock"
DEFAULT_VMS_URI = "qemu+unix:///system?socket=/run/truenas_libvirt/libvirt-sock"


class DomainManagers:
    def __init__(
            self,
            connection_manager: ConnectionManager,
            containers_uri: str = DEFAULT_CONTAINERS_URI,
            vms_uri: str = DEFAULT_VMS_URI,
    ) -> None:
        self.connection_manager = connection_manager

        self.containers_connection = self.connection_manager.create(containers_uri)
        self.containers = DomainManager(self.containers_connection)

        self.vms_connection = self.connection_manager.create(vms_uri)
        self.vms = DomainManager(self.vms_connection)
