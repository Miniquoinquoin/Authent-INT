from fastapi import APIRouter

router = APIRouter(tags=["ops"])

from . import health, metrics  # noqa: E402,F401  (registers routes)
