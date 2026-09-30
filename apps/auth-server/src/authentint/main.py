from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from authentint import flows
from authentint import oidc
from authentint import ops
from authentint.audit.middleware import RequestIdMiddleware
from authentint.config import settings
from authentint.infra import database as db
from authentint.domain.errors import OAuthError, oauth_error_handler
from authentint.keys import keystore
from authentint.keys import routes as keys_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with db.Session() as s:
        await keystore.ensure_active_key(s)  # advisory lock inside: only one replica generates
    yield
    await db.engine.dispose()

def create_app() -> FastAPI:
    # No Swagger UI for end users
    app = FastAPI(lifespan=lifespan, docs_url=None)
    app.add_exception_handler(OAuthError, oauth_error_handler)
    app.add_middleware(RequestIdMiddleware)
    # Added last = outermost: error responses get CORS headers too. Allow-list, never "*" (ADR §16)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.public_base_url],
        allow_credentials=True,  # the interaction endpoints set the __Host-session cookie
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(oidc.router)
    app.include_router(flows.router)
    app.include_router(keys_routes.router)
    app.include_router(ops.router)
    return app

app = create_app()
