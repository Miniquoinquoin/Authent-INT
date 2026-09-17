"""The read-only view of the client's directory (§5b).

This module never imports the database and never exposes a write method. The
read-only guarantee is enforced by the shape of the Protocol, not by convention:
there is no `save`, no `create`, no `set_password` to call by accident.

`FixtureDirectory` is the fixture half of brick B7. `LdapDirectory` will be a
second implementation of the same Protocol at S5, and nothing else in the
codebase changes when it arrives.
"""

import json
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, EmailStr


class DirectoryUser(BaseModel):
    """§5b verbatim."""

    external_id: str  #: LDAP entryUUID — the join key, never the DN
    numero_fiscal: str
    nom: str
    prenom: str
    email: EmailStr
    groups: list[str] = []  #: raw group DNs, mapped to a role by us


class UserDirectory(Protocol):
    """Read-only view of the client's directory."""

    async def find_by_numero_fiscal(self, nf: str) -> DirectoryUser | None:
        """Attribute lookup. Never verifies credentials."""

    def list(self, modified_since: datetime | None = None) -> AsyncIterator[DirectoryUser]:
        """Incremental provisioning feed."""


class FixtureDirectory:
    """A JSON file standing in for the directory.

    **JSON, not LDIF.** The real adapter receives dicts from `bonsai`, so an
    LDIF parser would be code written for a consumer that never materialises.
    When the OpenLDAP container arrives in B7 it needs an LDIF seed — generate
    it from this file then (P§5).

    No `modified_since` filtering: the fixture has no change timestamps, and the
    incremental-vs-full decision is §17 Q6, which has not come back.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def _entries(self) -> list[DirectoryUser]:
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return [DirectoryUser.model_validate(entry) for entry in raw]

    async def find_by_numero_fiscal(self, nf: str) -> DirectoryUser | None:
        return next((e for e in self._entries() if e.numero_fiscal == nf), None)

    async def list(self, modified_since: datetime | None = None) -> AsyncIterator[DirectoryUser]:
        for entry in self._entries():
            yield entry
