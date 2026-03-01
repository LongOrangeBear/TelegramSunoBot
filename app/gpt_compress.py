"""Compress long prompts using OpenAI GPT to fit within API character limits."""

import logging
from typing import Optional

import httpx

from app.config import config

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Ты — помощник для сжатия описаний песен. "
    "Тебе дают описание песни на русском языке, которое слишком длинное. "
    "Твоя задача — переформулировать его МАКСИМАЛЬНО КОРОТКО (до {limit} символов), "
    "но ОБЯЗАТЕЛЬНО сохранив ВСЕ имена, факты, даты, события и ключевые детали. "
    "Убери воду, вводные слова, повторы. Используй сокращения. "
    "НЕ добавляй ничего нового. Пиши ТОЛЬКО сжатый текст, без пояснений."
)


async def compress_prompt(text: str, limit: int = 200) -> Optional[str]:
    """
    Use GPT to compress a long prompt to fit within the character limit.
    Returns compressed text, or None if compression fails.
    """
    if not config.openai_api_key:
        logger.warning("No OpenAI API key configured, skipping GPT compression")
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {
                            "role": "system",
                            "content": _SYSTEM_PROMPT.format(limit=limit),
                        },
                        {
                            "role": "user",
                            "content": f"Сожми это описание песни до {limit} символов:\n\n{text}",
                        },
                    ],
                    "max_tokens": 300,
                    "temperature": 0.3,
                },
            )
            response.raise_for_status()
            data = response.json()

            compressed = data["choices"][0]["message"]["content"].strip()

            # Safety: if GPT returned something longer, truncate
            if len(compressed) > limit:
                compressed = compressed[:limit]

            logger.info(
                f"GPT compressed prompt: {len(text)} -> {len(compressed)} chars"
            )
            return compressed

    except Exception as e:
        logger.error(f"GPT compression failed: {e}")
        return None
