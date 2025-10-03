import functools
import os

from xml.etree import ElementTree as etree


@functools.cache
def get_cpu_model_choices():
    """
    Parse CPU model choices from libvirt XML files.
    This function is cached to avoid re-parsing XML files on every call.
    Returns a dict of {model_name: model_name} for available CPU models.
    """
    base_path = '/usr/share/libvirt/cpu_map'
    index_file = os.path.join(base_path, 'index.xml')
    with open(index_file, 'r') as f:
        index_xml = etree.fromstring(f.read().strip())

    models = {}

    # Process architectures that virsh cpu-models supports
    # Note: arm is excluded as virsh cpu-models arm fails
    for arch in index_xml.findall('.//arch[@name]'):
        arch_name = arch.get('name')
        if arch_name not in ['x86', 'ppc64']:
            continue

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

    return models
