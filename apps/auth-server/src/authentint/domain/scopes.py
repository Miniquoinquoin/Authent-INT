from authentint.infra.models.identity import Role
from authentint.infra.models.oauth import OAuthClients


# Defines allowed scopes for each roles
ALLOWED: dict[Role, frozenset[str]] = {
    Role.admin: frozenset({"svc:admin.users", "svc:admin.audit", "svc:cadastre.write", "svc:cadastre.read", "svc:impots.write", "svc:impots.read"}),
    Role.agent: frozenset({"svc:cadastre.read", "svc:impots.write", "svc:impots.read"}),
    Role.contribuable: frozenset({"svc:impots.read"})
}

def grant(requested: set[str], role: Role, client: OAuthClients) -> set[str]:
    """
    """

    return requested & ALLOWED[role] & set(client.allowed_scopes)
