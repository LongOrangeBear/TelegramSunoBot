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
    database_url: str = os.getenv("DATABASE_URL", "postgresql://suno_bot:suno_bot@localhost:5432/suno_bot")

    # Suno API
    suno_api_url: str = os.getenv("SUNO_API_URL", "https://api.kie.ai")
    suno_api_key: str = os.getenv("SUNO_API_KEY", "")

    # Limits
    max_generations_per_hour: int = int(os.getenv("MAX_GENERATIONS_PER_HOUR", "30"))
    max_generations_per_user_per_day: int = int(os.getenv("MAX_GENERATIONS_PER_USER_PER_DAY", "10"))
    free_credits_on_signup: int = int(os.getenv("FREE_CREDITS_ON_SIGNUP", "2"))
    min_account_age_hours: int = int(os.getenv("MIN_ACCOUNT_AGE_HOURS", "24"))

    # Credit packages: (credits, stars_price)
    credit_packages: list = None

    def __post_init__(self):
        if not self.bot_token:
            raise ValueError("BOT_TOKEN is required")
        self.credit_packages = [
            {"credits": 5, "stars": 50, "label": "5💎 — ⭐50"},
            {"credits": 15, "stars": 130, "label": "15💎 — ⭐130"},
            {"credits": 50, "stars": 400, "label": "50💎 — ⭐400"},
            {"credits": 100, "stars": 750, "label": "100💎 — ⭐750"},
        ]


config = Config()
