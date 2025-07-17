import time
import uuid

from .domain.base.configuration import Time
from .domain.container.configuration import ContainerDomainConfiguration
from .domain.container.domain import ContainerDomain
from .domain.managers import DomainManagers
from .libvirtd.connection_manager import ConnectionManager
from .libvirtd.service_delegate import ServiceDelegate


class DummyServiceDelegate(ServiceDelegate):
    def is_started(self):
        return True


if __name__ == "__main__":
    cm = ConnectionManager(DummyServiceDelegate())
    dm = DomainManagers(cm)
    dm.containers.connection.register_domain_event_callback(lambda e: print(f"Container event: {e}"))

    d = ContainerDomain(
        configuration=ContainerDomainConfiguration(
            uuid=str(uuid.uuid4()),
            name="test",
            description="test",
            vcpus=1,
            cores=1,
            threads=1,
            cpuset=None,
            memory=512,
            time=Time.UTC,
            autostart=False,
            shutdown_timeout=90,
            devices=[],
            root="/mnt/tank/test",
            init="/bin/sleep 15",
        )
    )
    dm.containers.start(d)

    for i in range(10):
        print(".")
        time.sleep(1)

    dm.containers.stop(d)

    for i in range(10):
        print(".")
        time.sleep(1)

    """
    import pprint
    print([
        (d.name(), c.domain_state(d)) for d in c.list_domains()
    ])
    print(d.pid())
    """
