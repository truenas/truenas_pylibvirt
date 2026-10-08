from unittest.mock import Mock, patch

from truenas_pylibvirt.domain.container.domain import ContainerDomain

XML = """<domain><devices>
<interface type="bridge"><source bridge="br10"/><target dev="vnet12"/></interface>
</devices></domain>"""


def test_post_start_copies_bridge_mtu_to_host_veth():
    links = {"br10": Mock(mtu=9000), "vnet12": Mock(mtu=1500, index=46)}
    module = "truenas_pylibvirt.domain.container.domain"
    with (
        patch(f"{module}.netlink_route"),
        patch(f"{module}.get_link", side_effect=lambda sock, name: links[name]),
        patch(f"{module}.set_link_mtu") as set_link_mtu,
    ):
        ContainerDomain.post_start(Mock(), Mock(XMLDesc=Mock(return_value=XML)))

    assert set_link_mtu.call_args.args[1] == 9000
    assert set_link_mtu.call_args.kwargs == {"index": 46}
