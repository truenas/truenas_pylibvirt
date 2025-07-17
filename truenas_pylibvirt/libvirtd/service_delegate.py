class ServiceDelegate:
    def ensure_started(self):
        raise NotImplementedError()

    def stop(self):
        raise NotImplementedError()
