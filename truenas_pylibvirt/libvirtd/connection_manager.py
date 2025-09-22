import threading

import libvirt

from ..error import Error
from .connection import Connection
from .service_delegate import ServiceDelegate


class ConnectionManager:
    def __init__(self, service_delegate: ServiceDelegate):
        self.service_delegate = service_delegate
        self.connections: list[Connection] = []

        libvirt.virEventRegisterDefaultImpl()
        libvirt.registerErrorHandler(self._libvirt_error_handler, None)

        event_thread = threading.Thread(target=self._libvirt_event_loop, name='libvirt_event_loop')
        event_thread.setDaemon(True)
        event_thread.start()

    def create(self, uri):
        connection = Connection(self, uri)
        self.connections.append(connection)
        return connection

    def open(self, uri):
        self.service_delegate.ensure_started()

        try:
            return libvirt.open(uri)
        except libvirt.libvirtError as e:
            raise Error(f"Failed to open libvirt connection: {e}")

    def _libvirt_error_handler(self, _, error):
        pass

    def _libvirt_event_loop(self):
        while True:
            libvirt.virEventRunDefaultImpl()
