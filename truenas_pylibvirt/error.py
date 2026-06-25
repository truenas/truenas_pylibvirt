import libvirt

__all__ = ["Error", "DomainDoesNotExistError", "GuestAgentError", "is_no_domain_error"]


class Error(Exception):
    pass


class DomainDoesNotExistError(Error):
    pass


class GuestAgentError(Error):
    pass


def is_no_domain_error(exc: BaseException) -> bool:
    return (
        isinstance(exc, libvirt.libvirtError)
        and exc.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN
    )
