from fastapi import APIRouter

router = APIRouter(tags=["oidc"])

from . import discovery, jwks, authorize, token, userinfo, revoke, end_session
