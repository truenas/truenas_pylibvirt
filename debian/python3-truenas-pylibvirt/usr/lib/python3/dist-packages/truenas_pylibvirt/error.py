__all__ = ["Error", "DomainDoesNotExistError"]


class Error(Exception):
    pass


class DomainDoesNotExistError(Error):
    pass
