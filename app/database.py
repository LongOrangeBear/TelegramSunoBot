"""Database connection and models using raw asyncpg."""

import asyncpg
import logging
from datetime import datetime

from app.config import config

logger = logging.getLogger(__name__)

pool: asyncpg.Pool | None = None


async def init_db():
    """Create connection pool and initialize schema."""
    global pool
    pool = await asyncpg.create_pool(config.database_url, min_size=2, max_size=10)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    logger.info("Database initialized")


async def close_db():
    """Close the connection pool."""
    global pool
    if pool:
        await pool.close()
        pool = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id   BIGINT PRIMARY KEY,
    username      VARCHAR(255),
    first_name    VARCHAR(255),
    credits       INTEGER NOT NULL DEFAULT 0,
    free_generations_left INTEGER NOT NULL DEFAULT 0,
    content_violations INTEGER NOT NULL DEFAULT 0,
    is_blocked    BOOLEAN NOT NULL DEFAULT FALSE,
    referred_by   BIGINT,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    last_generation_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS generations (
    id            SERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES users(telegram_id),
    suno_song_ids TEXT[],
    prompt        TEXT,
    style         VARCHAR(255),
    voice_gender  VARCHAR(10),
    mode          VARCHAR(20) NOT NULL DEFAULT 'description',
    status        VARCHAR(20) NOT NULL DEFAULT 'pending',
    audio_urls    TEXT[],
    tg_file_ids   TEXT[],
    credits_spent INTEGER NOT NULL DEFAULT 0,
    rating        INTEGER,
    error_message TEXT,
    callback_chat_id  BIGINT,
    callback_message_id BIGINT,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS payments (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(telegram_id),
    tg_payment_id   VARCHAR(255),
    stars_amount    INTEGER NOT NULL,
    credits_purchased INTEGER NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_generations_user_id ON generations(user_id);
CREATE INDEX IF NOT EXISTS idx_generations_created_at ON generations(created_at);
CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id);

-- Migration: add new columns if they don't exist
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='referred_by') THEN
        ALTER TABLE users ADD COLUMN referred_by BIGINT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='generations' AND column_name='rating') THEN
        ALTER TABLE generations ADD COLUMN rating INTEGER;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='payments' AND column_name='payment_type') THEN
        ALTER TABLE payments ADD COLUMN payment_type VARCHAR(20) NOT NULL DEFAULT 'stars';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='payments' AND column_name='order_id') THEN
        ALTER TABLE payments ADD COLUMN order_id VARCHAR(64);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='payments' AND column_name='amount_rub') THEN
        ALTER TABLE payments ADD COLUMN amount_rub INTEGER NOT NULL DEFAULT 0;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='payments' AND column_name='tbank_payment_id') THEN
        ALTER TABLE payments ADD COLUMN tbank_payment_id VARCHAR(64);
    END IF;
END $$;
"""


# ─── User operations ───

async def get_or_create_user(telegram_id: int, username: str | None, first_name: str | None,
                             referred_by: int | None = None) -> dict:
    """Get existing user or create new one with free credits."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE telegram_id = $1", telegram_id)
        if row:
            return dict(row)
        # New user
        row = await conn.fetchrow(
            """INSERT INTO users (telegram_id, username, first_name, credits, free_generations_left, referred_by)
               VALUES ($1, $2, $3, $4, $5, $6)
               RETURNING *""",
            telegram_id, username, first_name,
            0,  # credits start at 0
            config.free_credits_on_signup,
            referred_by,
        )
        logger.info(f"New user registered: {telegram_id} ({username}), referred_by={referred_by}")
        return dict(row)


async def get_user(telegram_id: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE telegram_id = $1", telegram_id)
        return dict(row) if row else None


async def update_user_credits(telegram_id: int, delta: int) -> int:
    """Add (positive) or subtract (negative) credits. Returns new balance."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE users SET credits = credits + $2 WHERE telegram_id = $1 RETURNING credits",
            telegram_id, delta,
        )
        return row["credits"]


async def use_free_generation(telegram_id: int) -> bool:
    """Try to use a free generation. Returns True if successful."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE users
               SET free_generations_left = free_generations_left - 1
               WHERE telegram_id = $1 AND free_generations_left > 0
               RETURNING free_generations_left""",
            telegram_id,
        )
        return row is not None


async def update_last_generation(telegram_id: int):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET last_generation_at = NOW() WHERE telegram_id = $1",
            telegram_id,
        )


async def increment_content_violations(telegram_id: int) -> int:
    """Increment violations and block if >= 3. Returns new count."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE users
               SET content_violations = content_violations + 1,
                   is_blocked = CASE WHEN content_violations + 1 >= 3 THEN TRUE ELSE is_blocked END
               WHERE telegram_id = $1
               RETURNING content_violations, is_blocked""",
            telegram_id,
        )
        return row["content_violations"]


async def count_referrals(telegram_id: int) -> int:
    """Count how many users were referred by this user."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM users WHERE referred_by = $1",
            telegram_id,
        )
        return row["cnt"]


# ─── Generation operations ───

async def create_generation(user_id: int, prompt: str, style: str,
                            voice_gender: str | None, mode: str) -> int:
    """Create a generation record and return its ID."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO generations (user_id, prompt, style, voice_gender, mode, status)
               VALUES ($1, $2, $3, $4, $5, 'pending')
               RETURNING id""",
            user_id, prompt, style, voice_gender, mode,
        )
        return row["id"]


async def update_generation_callback_info(gen_id: int, chat_id: int, message_id: int):
    """Store chat_id and message_id for async callback delivery."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE generations SET callback_chat_id = $2, callback_message_id = $3 WHERE id = $1",
            gen_id, chat_id, message_id,
        )


async def get_generation_by_task_id(task_id: str) -> dict | None:
    """Find a generation by its Suno task_id (stored in suno_song_ids array)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM generations WHERE $1 = ANY(suno_song_ids) ORDER BY created_at DESC LIMIT 1",
            task_id,
        )
        return dict(row) if row else None


async def update_generation_status(gen_id: int, status: str, **kwargs):
    """Update generation status and optional fields."""
    sets = ["status = $2"]
    values = [gen_id, status]
    idx = 3

    if "suno_song_ids" in kwargs:
        sets.append(f"suno_song_ids = ${idx}")
        values.append(kwargs["suno_song_ids"])
        idx += 1
    if "audio_urls" in kwargs:
        sets.append(f"audio_urls = ${idx}")
        values.append(kwargs["audio_urls"])
        idx += 1
    if "tg_file_ids" in kwargs:
        sets.append(f"tg_file_ids = ${idx}")
        values.append(kwargs["tg_file_ids"])
        idx += 1
    if "credits_spent" in kwargs:
        sets.append(f"credits_spent = ${idx}")
        values.append(kwargs["credits_spent"])
        idx += 1
    if "error_message" in kwargs:
        sets.append(f"error_message = ${idx}")
        values.append(kwargs["error_message"])
        idx += 1
    if status in ("complete", "error"):
        sets.append(f"completed_at = ${idx}")
        values.append(datetime.utcnow())
        idx += 1

    query = f"UPDATE generations SET {', '.join(sets)} WHERE id = $1"
    async with pool.acquire() as conn:
        await conn.execute(query, *values)


async def update_generation_rating(gen_id: int, rating: int):
    """Save user rating for a generation."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE generations SET rating = $2 WHERE id = $1",
            gen_id, rating,
        )


async def get_user_generations(user_id: int, limit: int = 10) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM generations
               WHERE user_id = $1 AND status = 'complete'
               ORDER BY created_at DESC LIMIT $2""",
            user_id, limit,
        )
        return [dict(r) for r in rows]


async def get_generation(gen_id: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM generations WHERE id = $1", gen_id)
        return dict(row) if row else None


async def count_user_generations_today(user_id: int) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT COUNT(*) as cnt FROM generations
               WHERE user_id = $1 AND created_at >= CURRENT_DATE""",
            user_id,
        )
        return row["cnt"]


async def count_generations_last_hour() -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM generations WHERE created_at >= NOW() - INTERVAL '1 hour'"
        )
        return row["cnt"]


async def reset_user_daily_generations(user_id: int):
    """Reset the daily generation counter by moving today's timestamps to yesterday."""
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE generations
               SET created_at = created_at - INTERVAL '1 day'
               WHERE user_id = $1 AND created_at >= CURRENT_DATE""",
            user_id,
        )


async def get_stuck_generations(timeout_minutes: int = 10) -> list[dict]:
    """Find generations stuck in 'processing' for longer than timeout."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM generations
               WHERE status IN ('processing', 'pending')
                 AND created_at < NOW() - make_interval(mins := $1)
               ORDER BY created_at ASC""",
            timeout_minutes,
        )
        return [dict(r) for r in rows]


# ─── Payment operations ───

async def create_payment(user_id: int, tg_payment_id: str, stars: int, credits: int) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO payments (user_id, tg_payment_id, stars_amount, credits_purchased, status)
               VALUES ($1, $2, $3, $4, 'completed')
               RETURNING id""",
            user_id, tg_payment_id, stars, credits,
        )
        # Add credits to user
        await conn.execute(
            "UPDATE users SET credits = credits + $2 WHERE telegram_id = $1",
            user_id, credits,
        )
        return row["id"]


async def create_tbank_payment(
    user_id: int, order_id: str, amount_rub: int, credits: int,
    tbank_payment_id: str | None = None,
) -> int:
    """Create a T-Bank payment record (initially pending)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO payments
               (user_id, order_id, stars_amount, amount_rub, credits_purchased, payment_type, status, tbank_payment_id)
               VALUES ($1, $2, 0, $3, $4, 'tbank', 'pending', $5)
               RETURNING id""",
            user_id, order_id, amount_rub, credits, tbank_payment_id,
        )
        return row["id"]


async def complete_tbank_payment(order_id: str, tbank_payment_id: str) -> dict | None:
    """Mark a T-Bank payment as completed and add credits to user. Returns payment dict or None."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM payments WHERE order_id = $1 AND payment_type = 'tbank' AND status = 'pending'",
            order_id,
        )
        if not row:
            return None

        payment = dict(row)

        # Mark as completed
        await conn.execute(
            "UPDATE payments SET status = 'completed', tbank_payment_id = $2 WHERE id = $1",
            payment["id"], tbank_payment_id,
        )

        # Add credits to user
        await conn.execute(
            "UPDATE users SET credits = credits + $2 WHERE telegram_id = $1",
            payment["user_id"], payment["credits_purchased"],
        )

        return payment


# ─── Admin panel queries ───

async def admin_get_stats() -> dict:
    """Dashboard statistics."""
    async with pool.acquire() as conn:
        users_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        gens_count = await conn.fetchval("SELECT COUNT(*) FROM generations")
        gens_complete = await conn.fetchval("SELECT COUNT(*) FROM generations WHERE status = 'complete'")
        gens_today = await conn.fetchval(
            "SELECT COUNT(*) FROM generations WHERE created_at >= CURRENT_DATE"
        )
        payments_count = await conn.fetchval("SELECT COUNT(*) FROM payments")
        total_stars = await conn.fetchval("SELECT COALESCE(SUM(stars_amount), 0) FROM payments")
        total_credits_sold = await conn.fetchval(
            "SELECT COALESCE(SUM(credits_purchased), 0) FROM payments"
        )
        avg_rating = await conn.fetchval(
            "SELECT ROUND(AVG(rating)::numeric, 1) FROM generations WHERE rating IS NOT NULL"
        )
        return {
            "users_count": users_count,
            "gens_count": gens_count,
            "gens_complete": gens_complete,
            "gens_today": gens_today,
            "payments_count": payments_count,
            "total_stars": total_stars,
            "total_credits_sold": total_credits_sold,
            "avg_rating": avg_rating or "—",
        }


async def admin_get_users(limit: int = 100, offset: int = 0) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT u.*,
                      (SELECT COUNT(*) FROM generations g WHERE g.user_id = u.telegram_id) as gen_count,
                      (SELECT COUNT(*) FROM payments p WHERE p.user_id = u.telegram_id) as pay_count,
                      (SELECT COALESCE(SUM(p.stars_amount), 0) FROM payments p WHERE p.user_id = u.telegram_id) as total_stars,
                      (SELECT COUNT(*) FROM users r WHERE r.referred_by = u.telegram_id) as referral_count
               FROM users u
               ORDER BY u.created_at DESC
               LIMIT $1 OFFSET $2""",
            limit, offset,
        )
        return [dict(r) for r in rows]


async def admin_get_user_detail(telegram_id: int) -> dict | None:
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE telegram_id = $1", telegram_id)
        if not user:
            return None
        gens = await conn.fetch(
            """SELECT * FROM generations WHERE user_id = $1 ORDER BY created_at DESC LIMIT 50""",
            telegram_id,
        )
        pays = await conn.fetch(
            """SELECT * FROM payments WHERE user_id = $1 ORDER BY created_at DESC LIMIT 50""",
            telegram_id,
        )
        referral_count = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE referred_by = $1", telegram_id
        )
        return {
            "user": dict(user),
            "generations": [dict(g) for g in gens],
            "payments": [dict(p) for p in pays],
            "referral_count": referral_count,
        }


async def admin_get_generations(limit: int = 100, offset: int = 0) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT g.*, u.username, u.first_name
               FROM generations g
               LEFT JOIN users u ON g.user_id = u.telegram_id
               ORDER BY g.created_at DESC
               LIMIT $1 OFFSET $2""",
            limit, offset,
        )
        return [dict(r) for r in rows]


async def admin_get_payments(limit: int = 100, offset: int = 0) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT p.*, u.username, u.first_name
               FROM payments p
               LEFT JOIN users u ON p.user_id = u.telegram_id
               ORDER BY p.created_at DESC
               LIMIT $1 OFFSET $2""",
            limit, offset,
        )
        return [dict(r) for r in rows]
