"""AI Melody Bot — Entry Point."""

import asyncio
import logging
from datetime import datetime, timezone

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app import database as db
from app.texts import GENERATION_TIMEOUT
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.config import config
from app.database import init_db, close_db
from app.suno_api import close_suno_client
from app.handlers import common, generation, payments
from app.admin import create_admin_app
from app.handlers.callback import handle_suno_callback, handle_video_callback

GENERATION_TIMEOUT_MINUTES = 10
WATCHDOG_CHECK_INTERVAL = 120  # seconds

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Shared bot instance for admin panel
bot_instance: Bot | None = None
bot_start_time: datetime | None = None


async def on_startup(bot: Bot):
    global bot_start_time
    bot_start_time = datetime.now(timezone.utc)
    logger.info("Bot starting up...")
    await init_db()
    logger.info("Database initialized")

    me = await bot.get_me()
    logger.info(f"Bot @{me.username} started (id={me.id})")

    # Set only /start in the Telegram commands menu (removes old BotFather commands)
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать"),
    ])


async def on_shutdown(bot: Bot):
    logger.info("Bot shutting down...")
    await close_suno_client()
    await close_db()
    logger.info("Cleanup complete")


async def run_bot():
    """Start the Telegram bot polling."""
    global bot_instance
    bot_instance = Bot(
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
    logger.info("Starting bot polling...")
    await dp.start_polling(bot_instance, allowed_updates=dp.resolve_used_update_types())


async def run_admin():
    """Start the admin panel web server."""
    if not config.admin_token:
        logger.warning("ADMIN_TOKEN not set — admin panel disabled")
        return

    # Wait a moment for bot to initialize
    await asyncio.sleep(2)

    app = create_admin_app()
    # Pass bot_instance getter to admin app
    app["get_bot"] = lambda: bot_instance
    app["get_start_time"] = lambda: bot_start_time

    # Register callback routes on the same app
    app.router.add_post("/callback/suno", handle_suno_callback)
    app.router.add_post("/callback/video", handle_video_callback)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.admin_port)
    await site.start()
    logger.info(f"Admin panel started at http://localhost:{config.admin_port}/admin/?token={config.admin_token}")
    if config.callback_base_url:
        logger.info(f"Suno callback URL: {config.callback_base_url.rstrip('/')}/callback/suno")

    # Start generation watchdog
    asyncio.create_task(generation_watchdog())

    # Keep running
    while True:
        await asyncio.sleep(3600)


async def generation_watchdog():
    """Periodically check for stuck generations and notify users."""
    logger.info(f"Generation watchdog started (timeout={GENERATION_TIMEOUT_MINUTES}m, interval={WATCHDOG_CHECK_INTERVAL}s)")
    # Wait for bot to be ready
    await asyncio.sleep(10)

    while True:
        try:
            stuck = await db.get_stuck_generations(timeout_minutes=GENERATION_TIMEOUT_MINUTES)
            if stuck:
                logger.warning(f"Watchdog: found {len(stuck)} stuck generation(s)")

            for gen in stuck:
                gen_id = gen["id"]
                chat_id = gen.get("callback_chat_id")
                status_msg_id = gen.get("callback_message_id")

                # Mark as error
                await db.update_generation_status(
                    gen_id, "error", error_message="timeout"
                )
                logger.info(f"Watchdog: generation {gen_id} marked as timeout error")

                # Notify user
                if chat_id and bot_instance:
                    delivered = False
                    if status_msg_id:
                        try:
                            await bot_instance.edit_message_text(
                                chat_id=chat_id,
                                message_id=status_msg_id,
                                text=GENERATION_TIMEOUT,
                                parse_mode="HTML",
                            )
                            delivered = True
                        except Exception as e:
                            logger.warning(f"Watchdog: failed to edit msg for gen {gen_id}: {e}")

                    if not delivered:
                        try:
                            await bot_instance.send_message(
                                chat_id=chat_id,
                                text=GENERATION_TIMEOUT,
                                parse_mode="HTML",
                            )
                        except Exception as e:
                            logger.error(f"Watchdog: failed to send msg for gen {gen_id}: {e}")

        except Exception as e:
            logger.error(f"Watchdog error: {e}", exc_info=True)

        await asyncio.sleep(WATCHDOG_CHECK_INTERVAL)


async def main():
    await asyncio.gather(run_bot(), run_admin())


if __name__ == "__main__":
    asyncio.run(main())
