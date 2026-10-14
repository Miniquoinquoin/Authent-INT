import random

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


CLEANUP_PROBABILITY = 0.01  # ADR §8 "Nettoyage sans CronJob": 1 hit in 100 sweeps the expired buckets


async def hit(s: AsyncSession, bucket: str, limit: int, window: timedelta, cleanup: float = CLEANUP_PROBABILITY) -> bool:
    try:
        if random.random() < cleanup:
            # disk space only: an expired bucket is already reset by the upsert below, never read as is
            await s.execute(text("DELETE FROM rate_limits WHERE expires_at < now()"))
        count = await s.scalar(text(
                """
                INSERT INTO rate_limits (bucket, count, expires_at) VALUES (:b, 1, :w)
                ON CONFLICT (bucket) DO UPDATE SET
                    count = CASE WHEN rate_limits.expires_at < now() THEN 1 ELSE rate_limits.count + 1 END,
                    expires_at = CASE WHEN rate_limits.expires_at < now() THEN :w ELSE rate_limits.expires_at END
                RETURNING count
                """
            ),
            {"b": bucket, "w": datetime.now(UTC) + window}
        )
        return count <= limit
    except Exception:
        return False
