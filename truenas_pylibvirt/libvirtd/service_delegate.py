class ServiceDelegate:
    def ensure_started(self) -> None:
        raise NotImplementedError()

    def stop(self) -> None:
        raise NotImplementedError()
