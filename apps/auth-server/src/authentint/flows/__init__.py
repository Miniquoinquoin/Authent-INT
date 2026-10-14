from fastapi import APIRouter

router = APIRouter(tags=["interaction"])

from . import activation, interaction  # noqa: E402,F401  (registers routes)
