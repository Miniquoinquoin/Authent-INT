from contextlib import asynccontextmanager

from fastapi import FastAPI

from authentint import oidc
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
    app.include_router(oidc.router)
    app.include_router(keys_routes.router)
    return app

app = create_app()
