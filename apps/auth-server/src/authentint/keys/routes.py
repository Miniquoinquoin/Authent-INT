from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends

from authentint.security.bearer import require_scope
from authentint.infra.database import get_session
from authentint.keys import keystore
from authentint.audit import audit

router = APIRouter(tags=["key"])

@router.post("/admin/keys/rotate")
async def rotate(claims = Depends(require_scope("svc:admin.users")), session = Depends(get_session)):
    await keystore.rotate(session)         # next→active→retired, nouvelle next
    await audit.emit(session, "keys.rotated", actor=UUID(claims["sub"]), outcome="success", detail={})
    await session.commit()
