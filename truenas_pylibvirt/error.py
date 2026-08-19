import functools
from typing import Callable, ParamSpec, TypeVar

import libvirt

__all__ = [
    "Error", "DeviceNotFoundError", "DomainDoesNotExistError", "GuestAgentError", "is_no_domain_error",
    "libvirt_errors_as_error",
]

P = ParamSpec("P")
R = TypeVar("R")


class Error(Exception):
    pass


class DeviceNotFoundError(Error):
    """A device a domain is configured to pass through is not present on the host."""


class DomainDoesNotExistError(Error):
    pass


class GuestAgentError(Error):
    pass


def libvirt_errors_as_error(f: Callable[P, R]) -> Callable[P, R]:
    """Present a libvirt failure from a public entry point as this package's own error type.

    `libvirt.libvirtError` is libvirt's exception, not ours, and it is what libvirt raises for the
    ordinary things: refusing a generated domain definition, failing to launch the guest. A caller
    that wants to report those as anything other than a traceback has to import libvirt itself just
    to name the type, which defeats the point of this package existing.

    A domain that is already gone keeps its own type. libvirt reports that as an ordinary failure
    of whatever call raced with the undefine, and a caller treating "already gone" as nothing to do
    can only recognise it if the distinction survives this conversion.

    Only for the outermost layer. The handling underneath inspects libvirt error codes and has to
    keep seeing the original exception.
    """
    @functools.wraps(f)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return f(*args, **kwargs)
        except libvirt.libvirtError as e:
            if is_no_domain_error(e):
                raise DomainDoesNotExistError(str(e)) from e

            raise Error(str(e)) from e

    return wrapper


def is_no_domain_error(exc: BaseException) -> bool:
    return (
        isinstance(exc, libvirt.libvirtError)
        and exc.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN
    )
