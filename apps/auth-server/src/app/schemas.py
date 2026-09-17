"""Request and response shapes, and the single failure-response constants.

**One failure object, not one failure string** (§10, boundary 6). Every failure
branch of P§7 returns the *same instance*, so the enumeration property is
structural: a sixth handler cannot accidentally paraphrase it, and the
byte-identical test in P§9 tests something real.
"""

from datetime import datetime

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.config import settings


class Failure(BaseModel):
    detail: str


#: The one thing every failing login says — unknown numéro fiscal, wrong
#: password, account awaiting activation, locked, or disabled. Five branches,
#: one sentence, one latency (P§7 step 4).
FAILURE = Failure(
    detail=(
        "Identifiants invalides, ou compte non activé. "
        "Si un compte correspond, un e-mail vient de vous être envoyé."
    )
)

#: MFA has its own constant for the same reason, and says just as little: wrong,
#: expired and exhausted are indistinguishable (§9).
OTP_FAILURE = Failure(detail="Code invalide ou expiré.")

#: The interaction handle is gone or was never ours. Says nothing about which.
INTERACTION_FAILURE = Failure(detail="Session d'authentification expirée. Veuillez recommencer.")


def refuse(failure: Failure = FAILURE, status: int = 401) -> JSONResponse:
    """Render one of the constants above. The only way a flow says no."""
    return JSONResponse(status_code=status, content=failure.model_dump())


# --------------------------------------------------------------- interaction
class InteractionCreated(BaseModel):
    uid: str


class InteractionState(BaseModel):
    """What does this pending authentication need next?

    The server decides the stage. The client never carries identity state back
    to us — it cannot tamper with what it does not hold (§7).
    """

    stage: str


class LoginRequest(BaseModel):
    numero_fiscal: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=256)


class MfaVerifyRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


# ---------------------------------------------------------------- activation
class _ChosenPassword(BaseModel):
    password: str = Field(max_length=256)

    @field_validator("password")
    @classmethod
    def long_enough(cls, value: str) -> str:
        # Length only, no composition rule: ANSSI's own guidance, and §17 Q7 has
        # not come back with anything stricter.
        minimum = settings().password_min_length
        if len(value) < minimum:
            raise ValueError(f"Le mot de passe doit contenir au moins {minimum} caractères.")
        return value


class ActivationConfirm(_ChosenPassword):
    token: str = Field(min_length=1, max_length=256)


# ------------------------------------------------------------------------ me
class Me(BaseModel):
    nom: str
    prenom: str
    role: str
    statut: str
    session_ouverte_a: datetime
