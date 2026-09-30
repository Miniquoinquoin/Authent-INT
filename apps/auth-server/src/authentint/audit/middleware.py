import uuid

from contextvars import ContextVar
from starlette.middleware.base import BaseHTTPMiddleware # Using starlette for class style declaration (fastapi middleware is built on top of it)

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
client_ip_var: ContextVar[str] = ContextVar("client_ip", default="0.0.0.0")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        req_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request_id_var.set(req_id)
        client_ip_var.set(request.client.host if request.client else "0.0.0.0")
        response = await call_next(request)
        response.headers["x-request-id"] = req_id

        return response
