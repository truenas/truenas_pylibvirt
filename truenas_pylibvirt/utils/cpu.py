import functools
import os

from xml.etree import ElementTree as etree


# Translate libvirt cpu_map architecture names to TrueNAS arch_type values.
# Each libvirt arch maps to one or more TrueNAS arch_type values that share
# its CPU model set (e.g. x86_64 and i686 both consume libvirt's x86 models;
# libvirt's arm cpu_map ships only 64-bit cores so it maps to aarch64 only).
_ARCH_MAP = {
    'x86':   ('x86_64', 'i686'),
    'ppc64': ('ppc64',),
    'arm':   ('aarch64',),
}


@functools.cache
def get_cpu_model_choices() -> dict[str, dict[str, str]]:
    """
    Parse CPU model choices from libvirt XML files, grouped by guest arch.
    This function is cached to avoid re-parsing XML files on every call.
    Returns a dict of {arch_type: {model_name: model_name}} where arch_type
    matches TrueNAS VM arch_type values (e.g. 'x86_64', 'i686', 'aarch64',
    'ppc64'). Architectures absent from libvirt's cpu_map (e.g. 32-bit ARM)
    are also absent from the result.
    """
    base_path = '/usr/share/libvirt/cpu_map'
    index_file = os.path.join(base_path, 'index.xml')
    with open(index_file, 'r') as f:
        index_xml = etree.fromstring(f.read().strip())

    result: dict[str, dict[str, str]] = {}

    # Process architectures whose cpu_map XML files we parse
    for arch in index_xml.findall('.//arch[@name]'):
        arch_name = arch.get('name')
        truenas_archs = _ARCH_MAP.get(arch_name)
        if truenas_archs is None:
            continue

        models: dict[str, str] = {}
        # Process all include elements in the architecture
        for elem in arch.iter('include'):
            filename = elem.get('filename')
            if not filename:
                continue

            filepath = os.path.join(base_path, filename)
            try:
                with open(filepath, 'r') as f:
                    content = f.read().strip()
                    # Skip non-model files like features.xml, vendors.xml
                    if '<model name=' not in content:
                        continue

                    xml = etree.fromstring(content)
                    model = xml.find('.//model[@name]')
                    if model is not None:
                        name = model.get('name')
                        if name:
                            models[name] = name
            except (etree.ParseError, IOError, FileNotFoundError):
                # Skip files that can't be parsed or are not there
                continue

        if models:
            for truenas_arch in truenas_archs:
                result[truenas_arch] = models

    return result
