from pydantic import BaseModel
from uuid import UUID

from authentint.infra.models.identity import Role


class IdToken(BaseModel):
    """
    Defines a Pydantic model for the ID Token (who / when / why) so that no token with missing attributes can be provided.
    The attributes follow the OIDC spec.
    """

    iss: str
    sub: UUID
    aud: str
    exp: int
    iat: int
    auth_time: int
    nonce: str
    acr: str
    amr: list[str]
    sid: UUID
    name: str
    given_name: str
    family_name: str
    role: Role
