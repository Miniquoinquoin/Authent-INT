from fastapi import APIRouter

router = APIRouter(tags=["interaction"])

from . import interaction  # noqa: E402,F401  (registers routes)
