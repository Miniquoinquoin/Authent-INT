"""App factory, router mounting, pool lifecycle, health probes, log config.

No business logic lives here (§10).
"""

import json
import logging
import logging.config
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.config import settings
from app.flows import activation, interaction, me
from app.infra import cache, db
from app.infra.cache import CacheUnavailable

# The correlation id. §6 calls it "injected at the edge" — there is no edge
# until Caddy, so we generate one per request and Caddy overrides it later.
request_id: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    """One JSON line per record, on stdout.

    This is what §1 defers `audit_events` *against*: the deferral is only honest
    while these lines actually exist. Structured fields ride in a single `event`
    extra so they cannot collide with LogRecord attributes.

    Never the numéro fiscal, never an OTP, never a token (§5).
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id.get(),
        }
        payload.update(getattr(record, "event", {}))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": JsonFormatter}},
    "handlers": {"stdout": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["stdout"], "level": settings().log_level},
    "loggers": {
        # uvicorn ships its own handlers; route them through ours so the stream
        # is one format end to end.
        "uvicorn": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["stdout"], "level": "WARNING", "propagate": False},
    },
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.config.dictConfig(LOGGING)
    yield
    await db.engine.dispose()
    await cache._client.aclose()


app = FastAPI(
    title="Authent'INT — auth-server",
    version="0.1.0",
    summary="Authentication core: activation, password login, e-mail OTP, sessions.",
    lifespan=lifespan,
)


app.include_router(interaction.router)
app.include_router(activation.router)
app.include_router(me.router)


@app.exception_handler(CacheUnavailable)
async def valkey_down(_: Request, __: CacheUnavailable) -> JSONResponse:
    """Valkey is unreachable, so the request is rejected.

    Rate limiting **fails closed** (§11b rule 3): failing open would remove
    brute-force protection at precisely the moment something is going wrong.
    This is the one place degradation is deliberately ungraceful, and one
    handler is what makes it true for every route at once.
    """
    logging.getLogger(__name__).error(
        "cache.unavailable",
        extra={"event": {"event_type": "cache.unavailable", "outcome": "failure"}},
    )
    return JSONResponse(status_code=503, content={"detail": "Service momentanément indisponible."})


@app.middleware("http")
async def correlate(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex
    token = request_id.set(rid)
    try:
        response = await call_next(request)
    finally:
        request_id.reset(token)
    response.headers["x-request-id"] = rid
    return response


@app.get("/health/live", tags=["ops"])
async def live() -> dict[str, str]:
    """The process is up. Nothing else is asserted."""
    return {"status": "live"}


@app.get("/health/ready", tags=["ops"])
async def ready(response: Response) -> dict[str, object]:
    """Postgres and Valkey only.

    Deliberately **not** the directory: §5b rule 4 — the auth server serves
    logins without it, and a directory outage must not take readiness with it.
    """
    checks: dict[str, object] = {}
    for name, probe in (("postgres", db.ping), ("valkey", cache.ping)):
        try:
            await probe()
            checks[name] = "ok"
        except Exception as exc:  # noqa: BLE001 - the reason is the payload
            checks[name] = type(exc).__name__
    ok = all(v == "ok" for v in checks.values())
    response.status_code = 200 if ok else 503
    return {"status": "ready" if ok else "degraded", "checks": checks}
