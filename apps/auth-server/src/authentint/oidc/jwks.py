from fastapi import Depends

from . import router
from authentint.config import settings
from authentint.infra.database import get_session
from authentint.keys import keystore



@router.get("/.well-known/jwks.json")
async def jwks(session = Depends(get_session)):
    return await keystore.jwks(session)
