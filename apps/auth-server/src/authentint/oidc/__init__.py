from fastapi import APIRouter

router = APIRouter(tags=["oidc"])

from . import discovery, jwks, authorize, token
