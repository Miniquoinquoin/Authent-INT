"""
One image, configured per container: AUDIENCE picks which business routes this instance serves.
Run with `uvicorn --factory mockservices.main:create_app`.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from mockservices.auth import Verifier
from mockservices.config import Settings
from mockservices.jwks import JwksClient
from mockservices.resources import ROUTERS


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


def create_app(settings: Settings | None = None, jwks: JwksClient | None = None) -> FastAPI:
    settings = settings or Settings()
    if settings.audience not in ROUTERS:
        raise ValueError(f"AUDIENCE must be one of {sorted(ROUTERS)}, got {settings.audience!r}")
    jwks = jwks or JwksClient(
        settings.issuer,
        ca_bundle=settings.ca_bundle,
        cooldown=settings.jwks_refresh_cooldown,
        retry_delay=settings.jwks_retry_delay,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Best effort: the auth-server may start after us. If it isn't up, the first request retries.
        await jwks.ensure_loaded()
        yield
        await jwks.aclose()

    app = FastAPI(title=settings.service_name, lifespan=lifespan)
    app.state.settings = settings
    app.state.jwks = jwks
    app.state.verifier = Verifier(settings, jwks)
    app.include_router(ROUTERS[settings.audience])
    if settings.cors_origin:
        # The token travels in Authorization, never in a cookie: no allow_credentials
        app.add_middleware(CORSMiddleware, allow_origins=[settings.cors_origin],
                           allow_methods=["GET", "POST", "PATCH"], allow_headers=["Authorization", "Content-Type"])

    @app.get("/health/live", tags=["ops"])
    async def live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["ops"])
    async def ready():
        # Ready = we hold the issuer's keys, or can fetch them now: otherwise every token would get a 503
        if await jwks.ensure_loaded():
            return {"status": "ok"}
        return JSONResponse({"status": "jwks_unavailable"}, status_code=503)

    return app
