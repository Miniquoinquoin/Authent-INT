"""
/me (ADR §9 "Self-service") and /admin/users (ADR §9 "Admin") — B4.

/me is the token's `sub`, behind a token naming the IdP (`aud` authentint). /admin/users is
behind `svc:admin.users`. Neither ever answers the numero fiscal (it isn't even stored, only its
HMAC) nor a hash. Accounts are never deleted: the directory is the source of truth (ADR §6), so
DELETE disables. Every admin change is audited with the admin as actor and the target in detail.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter
from fastapi import BackgroundTasks
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi import Response
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authentint.audit import audit
from authentint.external.mailer import Mailer
from authentint.external.mailer import get_mailer
from authentint.flows import activation
from authentint.flows.login import ACCOUNT_LIMIT
from authentint.flows.login import ACCOUNT_WINDOW
from authentint.flows.login import account_bucket
from authentint.infra.database import get_session
from authentint.infra.models.identity import Role
from authentint.infra.models.identity import User
from authentint.infra.models.identity import UserStatus
from authentint.security import ratelimit
from authentint.security.bearer import current_user
from authentint.security.bearer import idp_claims
from authentint.security.bearer import require_scope
from authentint.security.passwords import NewPassword
from authentint.security.passwords import hash_password
from authentint.security.passwords import verify_password
from authentint.sessions import queries as sessions


router = APIRouter()

admin_users = require_scope("svc:admin.users")


class Me(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nom: str
    prenom: str
    email: str
    role: Role
    status: UserStatus

class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: NewPassword

class UserView(Me):
    external_id: str | None
    failed_login_count: int
    locked_until: datetime | None
    password_changed_at: datetime | None
    created_at: datetime
    updated_at: datetime

class UserPage(BaseModel):
    items: list[UserView]
    total: int

class UserPatch(BaseModel):
    role: Role | None = None
    status: UserStatus | None = None


@router.get("/me", response_model=Me, tags=["me"], responses={401: {"description": "No, invalid or non-IdP token"}})
async def me(user: User = Depends(current_user)):
    return user

@router.post("/me/password", status_code=204, tags=["me"], responses={
    401: {"description": "Wrong current password (or token)"},
    429: {"description": "Rate limited (same per-account bucket as login)"},
})
async def change_password(body: PasswordChange, claims: dict = Depends(idp_claims), user: User = Depends(current_user),
                          session: AsyncSession = Depends(get_session)):
    """The other devices are logged out; the one asking keeps its session."""

    # A stolen access token must not become a password oracle: guesses here fill the login bucket of the account
    ok = await ratelimit.hit(session, account_bucket(user.numero_fiscal_hmac), ACCOUNT_LIMIT, ACCOUNT_WINDOW)
    await session.commit()
    if not ok:
        raise HTTPException(429, "too_many_attempts")

    sid = UUID(claims["sid"])
    if user.password_hash is None or not await verify_password(user.password_hash, body.current_password):
        await audit.emit(session, "password.change_failed", actor=user.id, outcome="failure",
                         detail={"reason": "bad_credentials"}, session_id=sid)
        await session.commit()
        raise HTTPException(401, "invalid_credentials")

    user.password_hash = await hash_password(body.new_password)
    user.password_changed_at = func.now()
    await sessions.revoke_all(session, user.id, "password_changed", keep=sid)
    await audit.emit(session, "password.changed", actor=user.id, outcome="success", detail={}, session_id=sid)
    await session.commit()

    return Response(status_code=204)


async def target(session: AsyncSession, user_id: UUID) -> User:
    user = await session.get(User, user_id)

    if user is None:
        raise HTTPException(404, "unknown_user")

    return user

def not_self(claims: dict, user: User) -> None:
    """An admin can't lock themselves out: the last admin would leave nobody able to undo it."""

    if UUID(claims["sub"]) == user.id:
        raise HTTPException(409, "cannot_target_self")

async def admin_audit(session: AsyncSession, event_type: str, claims: dict, user: User, **detail) -> None:
    await audit.emit(session, event_type, actor=UUID(claims["sub"]), outcome="success",
                     detail={"target_user_id": str(user.id), **detail})


@router.get("/admin/users", response_model=UserPage, tags=["admin"])
async def list_users(role: Role | None = None, status: UserStatus | None = None,
                     q: str | None = Query(None, min_length=1, max_length=100, description="In nom, prenom or email"),
                     limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                     claims: dict = Depends(admin_users), session: AsyncSession = Depends(get_session)):
    query = select(User)
    if role is not None:
        query = query.where(User.role == role)
    if status is not None:
        query = query.where(User.status == status)
    if q is not None:
        query = query.where(or_(User.nom.ilike(f"%{q}%"), User.prenom.ilike(f"%{q}%"), User.email.ilike(f"%{q}%")))

    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    items = await session.scalars(query.order_by(User.nom, User.prenom, User.id).limit(limit).offset(offset))

    return UserPage(items=items.all(), total=total)

@router.get("/admin/users/{user_id}", response_model=UserView, tags=["admin"], responses={404: {"description": "Unknown user"}})
async def get_user(user_id: UUID, claims: dict = Depends(admin_users), session: AsyncSession = Depends(get_session)):
    return await target(session, user_id)

@router.patch("/admin/users/{user_id}", response_model=UserView, tags=["admin"], responses={
    404: {"description": "Unknown user"},
    409: {"description": "An admin demoting or disabling themselves"},
})
async def update_user(user_id: UUID, body: UserPatch, claims: dict = Depends(admin_users),
                      session: AsyncSession = Depends(get_session)):
    user = await target(session, user_id)
    changes = body.model_dump(exclude_none=True)

    if changes.get("role", Role.admin) != Role.admin or changes.get("status", UserStatus.active) != UserStatus.active:
        not_self(claims, user)

    for field, value in changes.items():
        setattr(user, field, value)
    if user.status in (UserStatus.locked, UserStatus.disabled):
        await sessions.revoke_all(session, user.id, "disabled_by_admin")

    await admin_audit(session, "admin.user.updated", claims, user, changes={k: v.value for k, v in changes.items()})
    await session.commit()
    await session.refresh(user)  # updated_at is set by the database

    return user

@router.delete("/admin/users/{user_id}", status_code=204, tags=["admin"], responses={
    404: {"description": "Unknown user"},
    409: {"description": "An admin disabling themselves"},
})
async def disable_user(user_id: UUID, claims: dict = Depends(admin_users), session: AsyncSession = Depends(get_session)):
    """Disables, never deletes (ADR §6): the account and its audit trail stay."""

    user = await target(session, user_id)
    not_self(claims, user)

    user.status = UserStatus.disabled
    await sessions.revoke_all(session, user.id, "disabled_by_admin")
    await admin_audit(session, "admin.user.disabled", claims, user)
    await session.commit()

    return Response(status_code=204)

@router.post("/admin/users/{user_id}/lock", response_model=UserView, tags=["admin"], responses={
    404: {"description": "Unknown user"},
    409: {"description": "An admin locking themselves"},
})
async def lock_user(user_id: UUID, claims: dict = Depends(admin_users), session: AsyncSession = Depends(get_session)):
    """Until an admin unlocks it (flows/login.is_locked), and logged out everywhere now."""

    user = await target(session, user_id)
    not_self(claims, user)

    user.status = UserStatus.locked
    await sessions.revoke_all(session, user.id, "locked_by_admin")
    await admin_audit(session, "admin.user.locked", claims, user)
    await session.commit()
    await session.refresh(user)  # updated_at is set by the database

    return user

@router.post("/admin/users/{user_id}/unlock", response_model=UserView, tags=["admin"], responses={404: {"description": "Unknown user"}})
async def unlock_user(user_id: UUID, claims: dict = Depends(admin_users), session: AsyncSession = Depends(get_session)):
    """Lifts an admin lock and the temporary lockout (ADR §16 "chemin de déverrouillage admin"). A disabled account stays disabled."""

    user = await target(session, user_id)

    if user.status == UserStatus.locked:
        user.status = UserStatus.active
    user.failed_login_count, user.locked_until = 0, None
    await admin_audit(session, "admin.user.unlocked", claims, user)
    await session.commit()
    await session.refresh(user)  # updated_at is set by the database

    return user

@router.post("/admin/users/{user_id}/resend-activation", status_code=202, tags=["admin"], responses={
    404: {"description": "Unknown user"},
    409: {"description": "The account is not pending activation"},
})
async def resend_activation(user_id: UUID, request: Request, background: BackgroundTasks, claims: dict = Depends(admin_users),
                            session: AsyncSession = Depends(get_session), mailer: Mailer = Depends(get_mailer)):
    user = await target(session, user_id)

    if user.status != UserStatus.pending_activation:
        raise HTTPException(409, "not_pending_activation")

    activation.issue_link(session, user, request.client.host if request.client else "0.0.0.0", background, mailer)
    await admin_audit(session, "admin.user.activation_resent", claims, user)
    await session.commit()

    return Response(status_code=202)
