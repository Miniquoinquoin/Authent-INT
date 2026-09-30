from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends

from authentint.security.bearer import require_scope
from authentint.infra.database import get_session
from authentint.keys import keystore
from authentint.audit import audit

router = APIRouter(tags=["key"])

@router.post("/admin/keys/rotate")
async def rotate(claims = Depends(require_scope("svc:admin.users")), s = Depends(get_session)):
    await keystore.rotate(s)         # next→active→retired, nouvelle next
    await audit.emit(s, "keys.rotated", actor=UUID(claims["sub"]), outcome="success", detail={})
