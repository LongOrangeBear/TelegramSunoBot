"""Telegram Suno Music Bot — Entry Point."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import config
from app.database import init_db, close_db
from app.suno_api import close_suno_client
from app.handlers import common, generation, payments

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def on_startup(bot: Bot):
    logger.info("Bot starting up...")
    await init_db()
    logger.info("Database initialized")

    me = await bot.get_me()
    logger.info(f"Bot @{me.username} started (id={me.id})")


async def on_shutdown(bot: Bot):
    logger.info("Bot shutting down...")
    await close_suno_client()
    await close_db()
    logger.info("Cleanup complete")


async def main():
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Register routers
    dp.include_router(common.router)
    dp.include_router(generation.router)
    dp.include_router(payments.router)

    # Lifecycle hooks
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Start polling
    logger.info("Starting polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
