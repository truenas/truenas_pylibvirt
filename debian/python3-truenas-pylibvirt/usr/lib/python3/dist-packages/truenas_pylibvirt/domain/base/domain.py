from typing import TYPE_CHECKING

from .configuration import BaseDomainConfiguration

if TYPE_CHECKING:
    from .xml import BaseDomainXmlGenerator


class BaseDomain:
    xml_generator_class = NotImplemented

    def __init__(self, configuration: BaseDomainConfiguration):
        self.configuration = configuration

    def xml_generator(self) -> "BaseDomainXmlGenerator":
        return self.xml_generator_class(self)

    def pid(self) -> int | None:
        raise NotImplementedError
