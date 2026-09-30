

from . import router
from authentint.config import settings
from authentint.domain.claims import IdToken
from authentint.domain.scopes import ALLOWED, OIDC_SCOPES

# Derived from domain/ so the published lists can't drift from what the server grants
SCOPES_SUPPORTED = sorted(OIDC_SCOPES.union(*ALLOWED.values()))
CLAIMS_SUPPORTED = list(IdToken.model_fields)

@router.get("/.well-known/openid-configuration")
async def discovery():
    issuer = settings.issuer

    return {"issuer": issuer, "authorization_endpoint": f"{issuer}/authorize", "token_endpoint": f"{issuer}/token",
            "jwks_uri": f"{issuer}/.well-known/jwks.json", "userinfo_endpoint": f"{issuer}/userinfo",
            "end_session_endpoint": f"{issuer}/end-session", "revocation_endpoint": f"{issuer}/revoke",
            "response_types_supported": ["code"], "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"], "id_token_signing_alg_values_supported": ["RS256"],
            "scopes_supported": SCOPES_SUPPORTED, "claims_supported": CLAIMS_SUPPORTED, "subject_types_supported": ["public"]}
