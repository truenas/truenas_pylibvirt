import libvirt

__all__ = ["Error", "DeviceNotFoundError", "DomainDoesNotExistError", "GuestAgentError", "is_no_domain_error"]


class Error(Exception):
    pass


class DeviceNotFoundError(Error):
    """A device a domain is configured to pass through is not present on the host."""


class DomainDoesNotExistError(Error):
    pass


class GuestAgentError(Error):
    pass


def is_no_domain_error(exc: BaseException) -> bool:
    return (
        isinstance(exc, libvirt.libvirtError)
        and exc.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN
    )
