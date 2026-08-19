import libvirt
import pytest

from truenas_pylibvirt import DomainDoesNotExistError, Error
from truenas_pylibvirt.error import libvirt_errors_as_error


def _libvirt_error(code, message="error"):
    e = libvirt.libvirtError(message)
    e.err = (code, None, message, None, None, None, None, -1, -1)
    return e


def test_a_libvirt_error_comes_out_as_ours():
    @libvirt_errors_as_error
    def entry_point():
        raise libvirt.libvirtError("XML error: unsupported configuration")

    with pytest.raises(Error) as exc_info:
        entry_point()

    assert not isinstance(exc_info.value, libvirt.libvirtError)
    assert "XML error: unsupported configuration" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, libvirt.libvirtError)


def test_a_domain_that_is_already_gone_keeps_its_own_type():
    """A call racing an undefine reports VIR_ERR_NO_DOMAIN, which callers treat as nothing to do."""
    @libvirt_errors_as_error
    def entry_point():
        raise _libvirt_error(libvirt.VIR_ERR_NO_DOMAIN, "Domain not found")

    with pytest.raises(DomainDoesNotExistError) as exc_info:
        entry_point()

    assert "Domain not found" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, libvirt.libvirtError)


def test_any_other_libvirt_code_is_not_a_missing_domain():
    @libvirt_errors_as_error
    def entry_point():
        raise _libvirt_error(libvirt.VIR_ERR_INTERNAL_ERROR)

    with pytest.raises(Error) as exc_info:
        entry_point()

    assert not isinstance(exc_info.value, DomainDoesNotExistError)


def test_our_own_errors_pass_through_unchanged():
    """Wrapping a DomainDoesNotExistError in a plain Error would lose what callers switch on."""
    raised = DomainDoesNotExistError("gone")

    @libvirt_errors_as_error
    def entry_point():
        raise raised

    with pytest.raises(DomainDoesNotExistError) as exc_info:
        entry_point()

    assert exc_info.value is raised


def test_everything_else_passes_through_unchanged():
    @libvirt_errors_as_error
    def entry_point():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        entry_point()


def test_the_return_value_and_arguments_survive():
    @libvirt_errors_as_error
    def entry_point(a, b, c=3):
        return a, b, c

    assert entry_point(1, b=2) == (1, 2, 3)
