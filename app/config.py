"""Application configuration from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

# Path to the .env file (project root)
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"



def persist_env_var(key: str, value: str):
    """Update or add an env var in .env file so changes persist across restarts."""
    import logging
    _logger = logging.getLogger(__name__)
    try:
        if _ENV_FILE.exists():
            lines = _ENV_FILE.read_text().splitlines()
        else:
            lines = []

        found = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                lines[i] = f"{key}={value}"
                found = True
                break

        if not found:
            lines.append(f"{key}={value}")

        _ENV_FILE.write_text("\n".join(lines) + "\n")
        _logger.info(f"Persisted {key}={value} to .env")
    except Exception as e:
        _logger.warning(f"Failed to persist {key} to .env: {e}")


# SunoAPI.org configuration
SUNO_API_BASE_URL = "https://api.sunoapi.org"
SUNO_AVAILABLE_MODELS = ["V4", "V4_5", "V4_5PLUS", "V4_5ALL", "V5"]


@dataclass
class Config:
    # Telegram
    bot_token: str = os.getenv("BOT_TOKEN", "")
    bot_username: str = os.getenv("BOT_USERNAME", "ai_melody_bot")

    # Database
    database_url: str = os.getenv("DATABASE_URL", "postgresql://ai_melody:ai_melody@localhost:5432/ai_melody")

    # Suno API (SunoAPI.org)
    suno_api_url: str = SUNO_API_BASE_URL
    suno_api_key: str = os.getenv("SUNO_API_KEY", "")
    suno_model: str = os.getenv("SUNO_MODEL", "V3_5")

    # Callback (public URL for Suno API to POST results)
    callback_base_url: str = os.getenv("CALLBACK_BASE_URL", "")

    # Available Suno models
    available_models: list = None

    # Limits
    max_generations_per_hour: int = int(os.getenv("MAX_GENERATIONS_PER_HOUR", "30"))
    max_generations_per_user_per_day: int = int(os.getenv("MAX_GENERATIONS_PER_USER_PER_DAY", "10"))
    free_credits_on_signup: int = int(os.getenv("FREE_CREDITS_ON_SIGNUP", "2"))
    credits_on_signup: int = int(os.getenv("CREDITS_ON_SIGNUP", "0"))
    min_account_age_hours: int = int(os.getenv("MIN_ACCOUNT_AGE_HOURS", "0"))
    min_telegram_user_id: int = int(os.getenv("MIN_TELEGRAM_USER_ID", "0"))

    # Russian language prefix in Suno prompts
    russian_language_prefix: bool = os.getenv("RUSSIAN_LANGUAGE_PREFIX", "1") == "1"

    # Video generation (MP4) after audio is ready
    video_generation_enabled: bool = os.getenv("VIDEO_GENERATION_ENABLED", "0") == "1"

    # Unlock price for preview tracks (free generations)
    unlock_price_stars: int = int(os.getenv("UNLOCK_PRICE_STARS", "75"))
    unlock_price_rub: int = int(os.getenv("UNLOCK_PRICE_RUB", "100"))

    # Preview settings (for free generations)
    preview_start_percent: int = int(os.getenv("PREVIEW_START_PERCENT", "33"))
    preview_duration_sec: int = int(os.getenv("PREVIEW_DURATION_SEC", "30"))

    # Admin panel
    admin_token: str = os.getenv("ADMIN_TOKEN", "")
    admin_port: int = int(os.getenv("ADMIN_PORT", "8080"))

    # T-Bank (Tinkoff) acquiring
    tbank_terminal_key: str = os.getenv("TBANK_TERMINAL_KEY", "")
    tbank_password: str = os.getenv("TBANK_PASSWORD", "")
    tbank_enabled: bool = False  # set in __post_init__

    # Credit packages: (credits, stars_price)
    credit_packages: list = None
    credit_packages_rub: list = None

    def __post_init__(self):
        if not self.bot_token:
            raise ValueError("BOT_TOKEN is required")
        self.available_models = list(SUNO_AVAILABLE_MODELS)
        if self.suno_model not in self.available_models:
            self.suno_model = self.available_models[0]
        self.credit_packages = [
            {"credits": 1, "stars": 75, "label": "1🎵 — ⭐75"},
            {"credits": 3, "stars": 210, "label": "3🎵 — ⭐210"},
            {"credits": 5, "stars": 325, "label": "5🎵 — ⭐325"},
            {"credits": 10, "stars": 600, "label": "10🎵 — ⭐600"},
            {"credits": 50, "stars": 2500, "label": "50🎵 — ⭐2500"},
        ]
        self.credit_packages_rub = [
            {"credits": 1, "rub": 100, "label": "1🎵 — 100₽"},
            {"credits": 3, "rub": 280, "label": "3🎵 — 280₽"},
            {"credits": 5, "rub": 450, "label": "5🎵 — 450₽"},
            {"credits": 10, "rub": 800, "label": "10🎵 — 800₽"},
            {"credits": 50, "rub": 3500, "label": "50🎵 — 3500₽"},
        ]
        self.tbank_enabled = bool(self.tbank_terminal_key)


config = Config()
