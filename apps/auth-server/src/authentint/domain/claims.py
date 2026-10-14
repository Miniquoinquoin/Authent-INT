from pydantic import BaseModel
from uuid import UUID

from authentint.infra.models.identity import Role


class RefreshedIdToken(BaseModel):
    """
    The ID token re-issued by the refresh_token grant: every IdToken claim but `nonce`.
    OIDC Core §12.2: the refresh request carries no nonce, so there is none to echo. A separate model,
    rather than an optional field, keeps IdToken strict: a code-flow ID token still can't lose its nonce.
    """

    iss: str
    sub: UUID
    aud: str
    exp: int
    iat: int
    auth_time: int
    acr: str
    amr: list[str]
    sid: UUID
    name: str
    given_name: str
    family_name: str
    role: Role
    at_hash: str  # OIDC Core §3.1.3.6: binds this ID token to the access token issued with it


class IdToken(RefreshedIdToken):
    """
    Defines a Pydantic model for the ID Token (who / when / why) so that no token with missing attributes can be provided.
    The attributes follow the OIDC spec.
    """

    nonce: str


class AccessToken(BaseModel):
    """
    The access token presented to Resource Servers (RFC 9068 profile, header `typ: at+jwt`).
    Frozen B0 contract: B2 signs it, B3 validates it.

    No `role` and no personal data: a Resource Server authorises on `scope` only (invariant 12),
    and never learns more about the user than the opaque `sub`.
    """

    iss: str
    sub: UUID
    aud: list[str]  # domain.scopes.audiences(granted scopes)
    client_id: str
    scope: str  # space-separated, as in RFC 6749
    exp: int
    iat: int
    jti: str  # unique per token: lets /revoke and the audit point at one token
    sid: UUID  # ends with the session: logout and device revocation
    acr: str
