"""The stage machine: the ordering of P§7, step by step.

Orchestration only. It never hashes, never mails, and never builds a Valkey key
itself — those belong to `security`, `infra.mailer` and `infra.cache` (§10).

Built as the §7 interaction API from the start rather than as an ad-hoc login
route. The shape costs nothing extra today and means the frontend, this machine
and every test written here survive B2 untouched: `/authorize` takes over
`POST /interaction`, and consent becomes a third entry in `STAGES`.
"""

import logging
import smtplib
import uuid as uuidlib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import security, sessions
from app.config import settings
from app.flows.activation import issue_activation
from app.infra import cache, mailer
from app.infra.db import get_db
from app.models import Status, User
from app.schemas import (
    FAILURE,
    INTERACTION_FAILURE,
    OTP_FAILURE,
    Failure,
    InteractionCreated,
    InteractionState,
    LoginRequest,
    MfaVerifyRequest,
    refuse,
)

log = logging.getLogger(__name__)
router = APIRouter(tags=["interaction"])

#: The stages this phase knows. B2 adds `consent` between `mfa` and `done` —
#: one entry and one handler, not a refactor (§9's "seam, not scaffolding").
STAGE_LOGIN = "login"
STAGE_MFA = "mfa"
STAGE_DONE = "done"
STAGES = (STAGE_LOGIN, STAGE_MFA, STAGE_DONE)

THROTTLED = Failure(detail="Trop de tentatives. Réessayez dans quelques minutes.")
MAIL_DOWN = Failure(detail="L'envoi du code a échoué. Réessayez dans un instant.")


def _event(name: str, **fields: object) -> dict[str, dict[str, object]]:
    return {"event": {"event_type": name, "outcome": "failure" if name.endswith(("failure", "refused")) else "success", **fields}}


async def _stage(uid: str, expected: str) -> dict | None:
    """The interaction state, if it exists and is at the expected stage.

    Never trust the client's claim about which stage it is on (§8 step 8): the
    stage is read from server-side state, and the client only ever holds `uid`.
    """
    state = await cache.interaction_get(uid)
    if state is None or state.get("stage") != expected:
        return None
    return state


@router.post("/interaction", response_model=InteractionCreated, status_code=201)
async def start() -> InteractionCreated:
    """Mint a `uid`.

    **Temporary.** `/authorize` takes this over at S2, after validating
    `client_id`, `redirect_uri` and PKCE (§8 step 7). Everything below it stays.
    """
    uid = await cache.interaction_create({"stage": STAGE_LOGIN})
    return InteractionCreated(uid=uid)


@router.get("/interaction/{uid}", response_model=InteractionState)
async def state(uid: str) -> InteractionState | JSONResponse:
    """What does this pending authentication need next?"""
    current = await cache.interaction_get(uid)
    if current is None:
        return refuse(INTERACTION_FAILURE, status=410)
    return InteractionState(stage=current["stage"])


@router.post("/interaction/{uid}/login", response_model=InteractionState)
async def login(
    uid: str,
    body: LoginRequest,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> InteractionState | JSONResponse:
    """Numéro fiscal + mot de passe.

    Five failure branches — unknown, wrong password, awaiting activation,
    locked, disabled — and all five return the identical body with the identical
    latency.
    """
    cfg = settings()
    if await _stage(uid, STAGE_LOGIN) is None:
        return refuse(INTERACTION_FAILURE, status=410)

    # Per IP *and* per account, separately, and before anything touches the
    # database. Valkey unreachable raises, and the handler in main.py turns that
    # into a 503: rejecting is the point (§11b rule 3).
    ip = sessions.client_ip(request) or "unknown"
    within_ip = await cache.rate_limit_hit("login:ip", ip, cfg.rl_login_ip, cfg.rl_login_ip_window_s)
    within_account = await cache.rate_limit_hit(
        "login:nf", security.pseudonym(body.numero_fiscal), cfg.rl_login_account, cfg.rl_login_account_window_s
    )
    if not (within_ip and within_account):
        log.info("login.throttled", extra=_event("login.throttled", ip=ip))
        return refuse(THROTTLED, status=429)

    user = await db.scalar(select(User).where(User.numero_fiscal == body.numero_fiscal))

    # Always verify, against a dummy hash when there is no user and when the
    # account has no password yet. Timing must not become the oracle the
    # response body is not (P§7 step 4).
    stored = user.password_hash if user and user.password_hash else security.DUMMY_HASH
    password_ok = await security.verify_password(stored, body.password)

    now = datetime.now(UTC)
    if user is None:
        log.info("login.failure", extra=_event("login.failure", reason="unknown", ip=ip))
        return refuse(FAILURE)

    if user.status is Status.DISABLED:
        # The branch §5's sync writes. A user whose directory entry vanished
        # must not be able to log in, and must not learn that this is why.
        log.info("login.failure", extra=_event("login.failure", reason="disabled", user_id=str(user.id), ip=ip))
        return refuse(FAILURE)

    if user.status is Status.LOCKED:
        if user.locked_until is not None and user.locked_until > now:
            log.info("login.failure", extra=_event("login.failure", reason="locked", user_id=str(user.id), ip=ip))
            return refuse(FAILURE)
        # The backoff has run out. There is no unlock job: a `locked_until` in
        # the past simply reads as unlocked.
        user.status = Status.ACTIVE if user.password_hash else Status.PENDING_ACTIVATION
        user.failed_login_count = 0
        user.locked_until = None
        await db.commit()

    if user.status is Status.PENDING_ACTIVATION:
        token = await issue_activation(db, user, ip)
        # After the response, not during it. An SMTP round trip on one branch
        # and not the others is precisely the timing oracle this flow avoids.
        background.add_task(mailer.send_activation, user.email, user.prenom, token)
        return refuse(FAILURE)

    if not password_ok:
        user.failed_login_count += 1
        if user.failed_login_count >= cfg.login_max_failures:
            user.status = Status.LOCKED
            user.locked_until = now + timedelta(seconds=cfg.login_lockout_backoff_s)
            log.info("account.locked", extra=_event("account.locked", user_id=str(user.id), ip=ip))
        await db.commit()
        log.info("login.failure", extra=_event("login.failure", reason="password", user_id=str(user.id), ip=ip))
        return refuse(FAILURE)

    user.failed_login_count = 0
    await db.commit()

    await cache.interaction_set(
        uid, {"stage": STAGE_MFA, "user_id": str(user.id), "auth_time": now.isoformat()}
    )
    log.info("login.success", extra=_event("login.success", user_id=str(user.id), ip=ip))
    return InteractionState(stage=STAGE_MFA)


@router.post("/interaction/{uid}/mfa/send", response_model=InteractionState)
async def mfa_send(uid: str, db: AsyncSession = Depends(get_db)) -> InteractionState | JSONResponse:
    """E-mail a six-digit code."""
    cfg = settings()
    current = await _stage(uid, STAGE_MFA)
    if current is None:
        return refuse(INTERACTION_FAILURE, status=410)

    if not await cache.rate_limit_hit("otp:send", uid, cfg.rl_otp_send, cfg.rl_otp_send_window_s):
        return refuse(THROTTLED, status=429)

    user = await db.scalar(select(User).where(User.id == uuidlib.UUID(current["user_id"])))
    if user is None:
        return refuse(INTERACTION_FAILURE, status=410)

    code, code_hash = await security.new_otp()
    # The hash, never the plaintext code (§6).
    await cache.otp_put(uid, code_hash, purpose="login")
    try:
        await mailer.send_otp(user.email, code)
    except (smtplib.SMTPException, OSError):
        # Fail loudly. Never fall back to skipping MFA (§11.6) — a mail outage
        # must degrade into "you cannot log in", never into "you are logged in".
        log.exception("otp.send_failed", extra=_event("otp.send_failed", user_id=str(user.id)))
        return refuse(MAIL_DOWN, status=502)

    return InteractionState(stage=STAGE_MFA)


@router.post("/interaction/{uid}/mfa/verify", response_model=InteractionState)
async def mfa_verify(
    uid: str,
    body: MfaVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Verify the code, open the session, set the cookie."""
    cfg = settings()
    current = await _stage(uid, STAGE_MFA)
    if current is None:
        return refuse(INTERACTION_FAILURE, status=410)

    challenge = await cache.otp_get(uid)
    if challenge is None:
        # Expired, never issued, or already consumed. One answer for all three.
        return refuse(OTP_FAILURE)

    attempts = await cache.otp_attempt(uid)
    if attempts > cfg.otp_max_attempts:
        await cache.otp_consume(uid)
        return refuse(OTP_FAILURE)

    if not await security.verify_otp(challenge["code_hash"], body.code):
        if attempts >= cfg.otp_max_attempts:
            # Consume on exhaustion as well as on success (§9).
            await cache.otp_consume(uid)
            log.info("mfa.exhausted", extra=_event("mfa.exhausted", uid_hash=security.pseudonym(uid)))
        log.info("mfa.failure", extra=_event("mfa.failure", attempts=attempts))
        return refuse(OTP_FAILURE)

    await cache.otp_consume(uid)
    user = await db.scalar(select(User).where(User.id == uuidlib.UUID(current["user_id"])))
    if user is None or user.status is not Status.ACTIVE:
        return refuse(FAILURE)

    _, token = await sessions.create(db, user, request)
    await cache.interaction_drop(uid)

    response = JSONResponse(InteractionState(stage=STAGE_DONE).model_dump())
    sessions.set_cookie(response, token)
    return response
