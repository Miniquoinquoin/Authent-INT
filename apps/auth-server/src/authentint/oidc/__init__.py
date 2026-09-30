from fastapi import APIRouter

router = APIRouter(tags=["oidc"])

from . import discovery, jwks, authorize  # noqa: E402,F401  (registers routes)
