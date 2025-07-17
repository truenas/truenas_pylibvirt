from dataclasses import dataclass
import enum

from ..base.configuration import BaseDomainConfiguration


@dataclass(kw_only=True)
class ContainerIdmapConfigurationItem:
    target: int
    count: int


@dataclass(kw_only=True)
class ContainerIdmapConfiguration:
    uid: ContainerIdmapConfigurationItem
    gid: ContainerIdmapConfigurationItem


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
