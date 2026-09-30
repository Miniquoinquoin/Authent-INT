from typing import Protocol


import json
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, EmailStr

from authentint.infra.models.identity import Role


ROLE_BY_GROUP = {"cn=admins": Role.admin, "cn=agents": Role.agent, "cn=contribuables": Role.contribuable}


class DirectoryUser(BaseModel):
    external_id: str
    numero_fiscal: str
    nom: str
    prenom: str
    email: EmailStr
    groups: list[str]

# Defines an abstraction for the LDAP "directory" so that it can later be switched from json to the real LDAP
class UserDirectory(Protocol):
    async def find_by_numero_fiscal(self, nf: str) -> DirectoryUser | None: ...
    def list_all(self) -> Iterator[DirectoryUser]: ...

class JsonDirectory:
    def __init__(self, path: str):
        users = [DirectoryUser(**u) for u in json.loads(Path(path).read_text())]
        self._by_nf = {u.numero_fiscal: u for u in users}
        assert len(self._by_nf) == len(users), "numero_fiscal en double dans l'annuaire"

    async def find_by_numero_fiscal(self, nf: str) -> DirectoryUser | None:
        return self._by_nf.get(nf)

    def list_all(self) -> Iterator[DirectoryUser]:
        return iter(self._by_nf.values())


def role_for(groups: list[str]) -> Role:
    roles = {ROLE_BY_GROUP.get(dn.split(",")[0].lower()) for dn in groups}
    for role in (Role.admin, Role.agent):
        if role in roles:
            return role
    return Role.contribuable
