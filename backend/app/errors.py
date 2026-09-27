class ServiceError(Exception):
    """Business-rule failure. Rendered as {"detail": {"error": code, "message": ..., ...}}."""

    def __init__(self, status_code: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.extra = extra
