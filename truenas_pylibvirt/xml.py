from xml.etree import ElementTree


def xml_element(
        tag: str,
        *,
        attributes: dict[str, str] | None = None,
        children: list[ElementTree.Element] | None = None,
        text: str | None = None,
) -> ElementTree.Element:
    element = ElementTree.Element(tag, **(attributes or {}))  # type: ignore[arg-type]

    for child in children or []:
        element.append(child)

    if text is not None:
        element.text = text

    return element
