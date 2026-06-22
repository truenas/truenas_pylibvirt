import libvirt

from truenas_pylibvirt import is_no_domain_error


def _libvirt_error(code):
    e = libvirt.libvirtError("error")
    e.err = (code, None, "message", None, None, None, None, -1, -1)
    return e


def test_true_for_no_domain():
    assert is_no_domain_error(_libvirt_error(libvirt.VIR_ERR_NO_DOMAIN)) is True


def test_false_for_other_libvirt_error():
    assert is_no_domain_error(_libvirt_error(libvirt.VIR_ERR_INTERNAL_ERROR)) is False


def test_false_for_non_libvirt_exception():
    assert is_no_domain_error(ValueError("nope")) is False
