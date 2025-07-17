from xml.etree import ElementTree


def xml_element(
        tag,
        *,
        attributes: dict[str, str] | None = None,
        children: list | None = None,
        text: str | None = None,
):
    element = ElementTree.Element(tag, **(attributes or {}))

    for child in children or []:
        element.append(child)

    if text is not None:
        element.text = text

    return element
