"""
The numero fiscal is never stored: only its HMAC (ADR §8, §10; decision: pseudonymisation).

Why HMAC and not SHA-256: a numero fiscal has only 13 digits (10^13 values). A plain
SHA-256 of every one of them can be computed in hours, which turns a stolen table back
into numeros fiscaux. An HMAC needs the secret key, which lives in the environment
(NUMERO_FISCAL_KEY), never in the database.

One-way on purpose: nothing needs to read a numero fiscal back. Login computes the HMAC
of what was typed and looks that up. The directory remains the source of truth.

The SAME formula is copied in the migration that converted the existing rows
(alembic/versions/*_numero_fiscal_hmac.py): change one, change both, or nobody can log in.
"""

import hashlib
import hmac

from authentint.config import settings


def numero_fiscal_digest(numero_fiscal: str) -> str:
    """HMAC-SHA256 of the numero fiscal with NUMERO_FISCAL_KEY, as 64 hexadecimal characters."""

    key = settings.numero_fiscal_key.encode()
    message = numero_fiscal.encode()

    return hmac.new(key, message, hashlib.sha256).hexdigest()
