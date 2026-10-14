"""
Fake business endpoints. Deterministic data, and nothing about the user but the opaque `sub`:
the access token carries no personal data (domain/claims.py AccessToken), so neither do we.
Writes are acknowledged, never persisted: the point is the 200 / 401 / 403, not the data.
"""

import hashlib
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from mockservices.auth import require_scope


Claims = dict[str, Any]


def _ref(sub: str, salt: str) -> str:
    return hashlib.sha256(f"{sub}:{salt}".encode()).hexdigest()[:8].upper()


# --- svc-impots ---------------------------------------------------------------------------

impots = APIRouter(tags=["impots"])


class NouveauDossier(BaseModel):
    impot: Literal["revenu", "taxe_fonciere"]
    annee: int = Field(ge=2000, le=2100)


@impots.get("/dossiers")
async def list_dossiers(claims: Annotated[Claims, Depends(require_scope("svc:impots.read"))]):
    sub = claims["sub"]
    return {
        "sub": sub,
        "dossiers": [
            {"id": f"IR-2025-{_ref(sub, 'ir')}", "impot": "revenu", "annee": 2025, "statut": "declare"},
            {"id": f"TF-2025-{_ref(sub, 'tf')}", "impot": "taxe_fonciere", "annee": 2025, "statut": "a_payer",
             "montant_eur": 812},
        ],
    }


@impots.post("/dossiers", status_code=201)
async def create_dossier(body: NouveauDossier, claims: Annotated[Claims, Depends(require_scope("svc:impots.write"))]):
    prefix = "IR" if body.impot == "revenu" else "TF"
    return {
        "id": f"{prefix}-{body.annee}-{_ref(claims['sub'], f'{body.impot}:{body.annee}')}",
        "impot": body.impot,
        "annee": body.annee,
        "statut": "brouillon",
        "cree_par": claims["sub"],
        "persiste": False,
    }


# --- svc-cadastre -------------------------------------------------------------------------

cadastre = APIRouter(tags=["cadastre"])

PARCELLES: dict[str, dict[str, Any]] = {
    p["id"]: p
    for p in (
        {"id": "AB-0012", "commune": "Evry-Courcouronnes", "section": "AB", "numero": "0012", "contenance_m2": 512, "nature": "sol"},
        {"id": "AB-0013", "commune": "Evry-Courcouronnes", "section": "AB", "numero": "0013", "contenance_m2": 1830, "nature": "jardin"},
        {"id": "ZC-0101", "commune": "Lisses", "section": "ZC", "numero": "0101", "contenance_m2": 24500, "nature": "terre"},
    )
}


class ModificationParcelle(BaseModel):
    contenance_m2: int | None = Field(default=None, gt=0)
    nature: str | None = Field(default=None, min_length=1, max_length=40)


@cadastre.get("/parcelles")
async def list_parcelles(claims: Annotated[Claims, Depends(require_scope("svc:cadastre.read"))]):
    return {"parcelles": list(PARCELLES.values())}


# svc:cadastre.write is granted to no role today (ADR §18 q.12): every real token gets a 403 here
@cadastre.patch("/parcelles/{parcelle_id}")
async def update_parcelle(
    parcelle_id: str,
    body: ModificationParcelle,
    claims: Annotated[Claims, Depends(require_scope("svc:cadastre.write"))],
):
    if parcelle_id not in PARCELLES:
        raise HTTPException(404, "unknown parcelle")
    return {**PARCELLES[parcelle_id], **body.model_dump(exclude_none=True), "modifie_par": claims["sub"],
            "persiste": False}


ROUTERS: dict[str, APIRouter] = {"svc-impots": impots, "svc-cadastre": cadastre}
