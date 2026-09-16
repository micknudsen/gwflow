"""Runtime failures are distinct from invalid authoring requests."""


class RuntimeFailure(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
