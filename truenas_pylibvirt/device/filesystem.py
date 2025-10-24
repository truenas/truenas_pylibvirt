import os
from dataclasses import dataclass

from .base import Device, DeviceXmlContext
from ..xml import xml_element


@dataclass(kw_only=True)
class FilesystemDevice(Device):

    target: str
    source: str

    def xml(self, context: DeviceXmlContext):
        return [
            xml_element(
                'filesystem',
                attributes={'type': 'mount'},
                children=[
                    xml_element('source', attributes={'dir': self.source}),
                    xml_element('target', attributes={'dir': self.target}),
                ],
            ),
        ]

    def identity_impl(self) -> str:
        return f'{self.source}:{self.target}'

    def is_available_impl(self) -> bool:
        return os.path.exists(self.source)

    def validate_impl(self) -> list[tuple[str, str]]:
        verrors = []
        if self.target == '/':
            verrors.append(('target', 'Target can\'t be root'))
        elif not os.path.isabs(self.target):
            verrors.append(('target', 'Target must be an absolute path'))
        if self.source == '/':
            verrors.append(('source', 'Source can\'t be root'))
        elif not os.path.isabs(self.source):
            verrors.append(('source', 'Source must be an absolute path'))
        elif not os.path.exists(self.source):
            verrors.append(('source', f'Source {self.source} does not exist'))
        return verrors
