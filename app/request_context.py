from contextvars import ContextVar
from uuid import uuid4


request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def current_request_id() -> str:
    request_id = request_id_var.get()
    if request_id:
        return request_id
    return str(uuid4())

