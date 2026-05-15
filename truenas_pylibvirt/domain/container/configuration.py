from dataclasses import dataclass
import enum

from ..base.configuration import BaseDomainConfiguration


@dataclass(kw_only=True)
class ContainerIdmapConfigurationItem:
    start: int
    target: int
    count: int


@dataclass(kw_only=True)
class ContainerIdmapConfiguration:
    uid: list[ContainerIdmapConfigurationItem]
    gid: list[ContainerIdmapConfigurationItem]

    def __post_init__(self) -> None:
        _validate_idmap_items("uid", self.uid)
        _validate_idmap_items("gid", self.gid)


def _validate_idmap_items(kind: str, items: list[ContainerIdmapConfigurationItem]) -> None:
    """Reject idmap lists the kernel would refuse.

    The Linux user namespace uid_map/gid_map interface (and the
    X-mount.idmap mount option that mirrors it) requires non-overlapping
    ranges on BOTH sides: no two entries may share a container-side UID,
    and no two may share a host-side UID. The kernel enforces this at
    namespace and idmapped-mount setup time; its errors there are opaque
    (EINVAL, "operation not supported") and surface late, after libvirt
    has already begun starting the domain.

    Validating here surfaces the specific conflicting ranges so the
    caller can diagnose the bad configuration without staring at a
    libvirt stack trace.
    """
    if not items:
        raise ValueError(f"At least one {kind} idmap entry is required")

    for item in items:
        if item.count <= 0:
            raise ValueError(f"{kind} idmap entry count must be positive (got {item.count})")
        if item.start < 0 or item.target < 0:
            raise ValueError(f"{kind} idmap entry start/target must be non-negative")

    sorted_by_ns = sorted(items, key=lambda i: i.start)
    for prev, curr in zip(sorted_by_ns, sorted_by_ns[1:]):
        if prev.start + prev.count > curr.start:
            raise ValueError(
                f"{kind} idmap container-side ranges overlap: "
                f"[{prev.start}, {prev.start + prev.count}) and [{curr.start}, {curr.start + curr.count})"
            )

    sorted_by_host = sorted(items, key=lambda i: i.target)
    for prev, curr in zip(sorted_by_host, sorted_by_host[1:]):
        if prev.target + prev.count > curr.target:
            raise ValueError(
                f"{kind} idmap host-side ranges overlap: "
                f"[{prev.target}, {prev.target + prev.count}) and [{curr.target}, {curr.target + curr.count})"
            )


class ContainerCapabilitiesPolicy(enum.Enum):
    DEFAULT = "default"
    ALLOW = "allow"
    DENY = "deny"


@dataclass(kw_only=True)
class ContainerDomainConfiguration(BaseDomainConfiguration):
    root: str
    init: str
    initdir: str | None
    initenv: dict[str, str]
    inituser: str | None
    initgroup: str | None
    idmap: ContainerIdmapConfiguration | None
    capabilities_policy: ContainerCapabilitiesPolicy
    capabilities_state: dict[str, bool]
