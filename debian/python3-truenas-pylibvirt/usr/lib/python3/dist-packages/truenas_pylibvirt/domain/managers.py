from .manager import DomainManager
from ..libvirtd.connection_manager import ConnectionManager


class DomainManagers:
    def __init__(
            self,
            connection_manager: ConnectionManager,
            containers_uri="lxc:///system?socket=/run/truenas_libvirt/libvirt-sock",
            vms_uri="qemu+unix:///system?socket=/run/truenas_libvirt/libvirt-sock",
    ):
        self.connection_manager = connection_manager

        self.containers_connection = self.connection_manager.create(containers_uri)
        self.containers = DomainManager(self.containers_connection)

        self.vms_connection = self.connection_manager.create(vms_uri)
        self.vms = DomainManager(self.vms_connection)
