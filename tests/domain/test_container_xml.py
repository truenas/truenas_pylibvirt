from unittest.mock import Mock

import pytest

from truenas_pylibvirt.device.nic import NICDevice, NICDeviceType
from truenas_pylibvirt.domain.container.xml import ContainerDomainXmlGenerator


@pytest.mark.parametrize("devices,tags", [
    ([], ["capabilities", "privnet"]),
    (
        [NICDevice(type_=NICDeviceType.BRIDGE, source="br0", model=None, mac=None, trust_guest_rx_filters=False)],
        ["capabilities"],
    ),
])
def test_features_privnet(devices, tags):
    mock_domain = Mock()
    mock_domain.configuration.capabilities_state = {}
    mock_domain.configuration.devices = devices

    generator = ContainerDomainXmlGenerator.__new__(ContainerDomainXmlGenerator)
    generator.domain = mock_domain

    assert [element.tag for element in generator._features_xml_children()] == tags
