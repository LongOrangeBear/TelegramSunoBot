"""Application configuration from environment variables."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # Telegram
    bot_token: str = os.getenv("BOT_TOKEN", "")

    # Database
    database_url: str = os.getenv("DATABASE_URL", "postgresql://ai_melody:ai_melody@localhost:5432/ai_melody")

    # Suno API
    suno_api_url: str = os.getenv("SUNO_API_URL", "https://api.kie.ai")
    suno_api_key: str = os.getenv("SUNO_API_KEY", "")
    suno_model: str = os.getenv("SUNO_MODEL", "V4")

    # Callback (public URL for Suno API to POST results)
    callback_base_url: str = os.getenv("CALLBACK_BASE_URL", "")

    # Available Suno models (KIE.ai v1 API)
    available_models: list = None

    # Limits
    max_generations_per_hour: int = int(os.getenv("MAX_GENERATIONS_PER_HOUR", "30"))
    max_generations_per_user_per_day: int = int(os.getenv("MAX_GENERATIONS_PER_USER_PER_DAY", "10"))
    free_credits_on_signup: int = int(os.getenv("FREE_CREDITS_ON_SIGNUP", "2"))
    min_account_age_hours: int = int(os.getenv("MIN_ACCOUNT_AGE_HOURS", "0"))
    min_telegram_user_id: int = int(os.getenv("MIN_TELEGRAM_USER_ID", "0"))

    # Admin panel
    admin_token: str = os.getenv("ADMIN_TOKEN", "")
    admin_port: int = int(os.getenv("ADMIN_PORT", "8080"))

    # Credit packages: (credits, stars_price)
    credit_packages: list = None

    def __post_init__(self):
        if not self.bot_token:
            raise ValueError("BOT_TOKEN is required")
        self.available_models = ["V3_5", "V4", "V4_5", "V4_5PLUS", "V5"]
        self.credit_packages = [
            {"credits": 5, "stars": 50, "label": "5💎 — ⭐50"},
            {"credits": 15, "stars": 130, "label": "15💎 — ⭐130"},
            {"credits": 50, "stars": 400, "label": "50💎 — ⭐400"},
            {"credits": 100, "stars": 750, "label": "100💎 — ⭐750"},
        ]


config = Config()
