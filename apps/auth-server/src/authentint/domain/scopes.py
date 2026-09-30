from authentint.infra.models.identity import Role
from authentint.infra.models.oauth import OAuthClients


# Standard OIDC scopes: they describe the identity itself, so every role may receive them (ADR §7)
OIDC_SCOPES: frozenset[str] = frozenset({"openid", "profile", "email", "offline_access"})

# Defines allowed service scopes for each role
ALLOWED: dict[Role, frozenset[str]] = {
    Role.admin: frozenset({"svc:admin.users", "svc:admin.audit", "svc:cadastre.write", "svc:cadastre.read", "svc:impots.write", "svc:impots.read"}),
    Role.agent: frozenset({"svc:cadastre.read", "svc:impots.write", "svc:impots.read"}),
    Role.contribuable: frozenset({"svc:impots.read"})
}

def grant(requested: set[str], role: Role, client: OAuthClients) -> set[str]:
    """
    granted = requested ∩ allowed(role) ∩ client.allowed_scopes (ADR §7).
    Reduces silently: the caller audits the difference with `requested`.
    """

    return requested & (ALLOWED[role] | OIDC_SCOPES) & set(client.allowed_scopes)

def audiences(scopes: set[str]) -> list[str]:
    """
    The access token `aud`: one Resource Server per service scope, "svc:impots.read" -> "svc-impots".
    Each Resource Server rejects a token whose `aud` does not contain its own name (ADR §11).
    """

    return sorted({"svc-" + s.removeprefix("svc:").split(".")[0] for s in scopes if s.startswith("svc:")})
