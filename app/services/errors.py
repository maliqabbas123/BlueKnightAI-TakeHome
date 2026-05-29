class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.code


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class PreconditionFailedError(AppError):
    status_code = 412
    code = "precondition_failed"


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"


class UpstreamError(AppError):
    status_code = 502
    code = "upstream_error"

