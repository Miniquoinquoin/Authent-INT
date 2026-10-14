from fastapi import APIRouter

router = APIRouter(tags=["interaction"])

from . import activation, interaction, reset  # noqa: E402,F401  (registers routes)
