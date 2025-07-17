from dataclasses import dataclass

from ..base.configuration import BaseDomainConfiguration


@dataclass(kw_only=True)
class ContainerDomainConfiguration(BaseDomainConfiguration):
    root: str
    init: str
