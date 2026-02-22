"""Callback endpoint for receiving Suno API results."""

import asyncio
import logging

import httpx
from aiohttp import web

from app import database as db
from app.config import config
from app.keyboards import track_kb, after_generation_kb
from app.suno_api import get_suno_client
from app.texts import GENERATION_COMPLETE, GENERATION_ERROR

logger = logging.getLogger(__name__)


async def handle_suno_callback(request: web.Request) -> web.Response:
    """
    Receive callback POST from SunoAPI.org when a generation task finishes.

    Expected payload (per API docs):
    {
        "code": 200,
        "msg": "All generated successfully.",
        "data": {
            "callbackType": "complete",
            "task_id": "...",
            "data": [
                {
                    "id": "...",
                    "audio_url": "https://...",
                    "stream_audio_url": "https://...",
                    "image_url": "https://...",
                    "title": "...",
                    "tags": "...",
                    "duration": 198.44,
                    ...
                }
            ]
        }
    }
    """
    try:
        payload = await request.json()
    except Exception:
        logger.warning("Callback: invalid JSON body")
        return web.json_response({"status": "error", "msg": "invalid json"}, status=400)

    code = payload.get("code")
    data = payload.get("data", {})
    task_id = data.get("task_id", "")
    callback_type = data.get("callbackType", "")

    logger.info(f"Suno callback received: code={code}, task_id={task_id}, type={callback_type}")

    if not task_id:
        logger.warning(f"Callback: no task_id in payload: {payload}")
        return web.json_response({"status": "ok"})

    # Handle intermediate callback types (text, first) — just log and acknowledge
    if callback_type in ("text", "first"):
        logger.info(f"Callback: intermediate type '{callback_type}' for task_id={task_id}, ignoring")
        return web.json_response({"status": "ok"})

    # Find generation by task_id (stored in suno_song_ids)
    gen = await db.get_generation_by_task_id(task_id)
    if not gen:
        logger.warning(f"Callback: generation not found for task_id={task_id}")
        return web.json_response({"status": "ok"})

    gen_id = gen["id"]
    user_id = gen["user_id"]

    # Idempotency: skip if already completed
    if gen["status"] == "complete":
        logger.info(f"Callback: generation {gen_id} already complete, skipping duplicate")
        return web.json_response({"status": "ok"})

    # Get bot instance from app context
    get_bot = request.app.get("get_bot")
    bot = get_bot() if get_bot else None

    if code == 200 and callback_type == "complete":
        # Success — extract audio URLs, image URLs, titles
        suno_data = data.get("data", [])

        audio_urls = []
        image_urls = []
        song_titles = []
        song_ids = []
        for s in suno_data:
            url = s.get("audio_url") or s.get("stream_audio_url", "")
            audio_urls.append(url)
            image_urls.append(s.get("image_url", ""))
            song_titles.append(s.get("title", "AI Melody Track"))
            song_ids.append(s.get("id", ""))

        if not audio_urls:
            logger.warning(f"Callback: no audio URLs in data for task_id={task_id}")
            return web.json_response({"status": "ok"})

        # Deduct credit
        user = await db.get_user(user_id)
        if user:
            if user["free_generations_left"] > 0:
                await db.use_free_generation(user_id)
            else:
                await db.update_user_credits(user_id, -1)
            await db.update_last_generation(user_id)

        await db.update_generation_status(
            gen_id, "complete",
            audio_urls=audio_urls,
            credits_spent=1,
        )

        # Send result to user via bot asynchronously (don't block the 200 response)
        if bot and gen.get("callback_chat_id"):
            asyncio.create_task(
                _deliver_result_to_user(bot, gen, gen_id, audio_urls, image_urls, song_titles, song_ids, task_id)
            )

        logger.info(f"Callback: generation {gen_id} completed with {len(audio_urls)} tracks")

    elif code != 200 or callback_type == "error":
        # Error
        error_msg = payload.get("msg", "Unknown error")
        await db.update_generation_status(gen_id, "error", error_message=error_msg)

        if bot and gen.get("callback_chat_id"):
            asyncio.create_task(
                _deliver_error_to_user(bot, gen, error_msg)
            )

        logger.warning(f"Callback: generation {gen_id} failed: {error_msg}")

    else:
        logger.info(f"Callback: unhandled code={code}, type={callback_type} for task_id={task_id}")

    return web.json_response({"status": "ok"})


async def _deliver_result_to_user(
    bot, gen: dict, gen_id: int,
    audio_urls: list[str], image_urls: list[str], song_titles: list[str],
    song_ids: list[str] = None, original_task_id: str = "",
):
    """Send generation results to the user in Telegram — SoNata-style (runs as background task)."""
    chat_id = gen["callback_chat_id"]
    status_msg_id = gen.get("callback_message_id")

    try:
        from aiogram.types import BufferedInputFile

        # Delete status message
        if status_msg_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=status_msg_id)
            except Exception:
                pass

        # SoNata-style delivery: per track — image, then audio with buttons
        for i, url in enumerate(audio_urls[:2]):
            if not url:
                continue
            try:
                img_url = image_urls[i] if i < len(image_urls) else ""
                title = song_titles[i] if i < len(song_titles) else f"Вариант {i+1}"

                # Send cover image
                if img_url:
                    try:
                        await bot.send_photo(
                            chat_id=chat_id,
                            photo=img_url,
                            caption=f"🎵 Обложка для трека: <b>{title}</b>",
                            parse_mode="HTML",
                        )
                    except Exception as e:
                        logger.warning(f"Callback: failed to send cover {i}: {e}")

                # Download and send audio file
                async with httpx.AsyncClient() as http:
                    resp = await http.get(url, timeout=60.0)
                    resp.raise_for_status()
                    audio_data = resp.content

                audio_file = BufferedInputFile(
                    audio_data,
                    filename=f"{title}.mp3",
                )
                await bot.send_audio(
                    chat_id=chat_id,
                    audio=audio_file,
                    title=title,
                    performer="AI Melody",
                    reply_markup=track_kb(gen_id, i),
                )
            except Exception as e:
                logger.error(f"Callback: failed to send track {i}: {e}")

        # Send after-generation keyboard
        await bot.send_message(
            chat_id=chat_id,
            text=GENERATION_COMPLETE,
            parse_mode="HTML",
            reply_markup=after_generation_kb(gen_id),
        )

        # Video generation (if enabled)
        if config.video_generation_enabled and original_task_id and song_ids:
            try:
                client = get_suno_client()
                for i, url in enumerate(audio_urls[:2]):
                    if not url or i >= len(song_ids) or not song_ids[i]:
                        continue
                    try:
                        title = song_titles[i] if i < len(song_titles) else f"Вариант {i+1}"
                        video_result = await client.generate_video(original_task_id, song_ids[i])
                        video_url = await client.wait_for_video(video_result["task_id"])
                        await bot.send_video(
                            chat_id=chat_id,
                            video=video_url,
                            caption=f"🎬 Видеоклип: <b>{title}</b>",
                            parse_mode="HTML",
                        )
                    except Exception as e:
                        logger.warning(f"Callback: video generation failed for track {i}: {e}")
            except Exception as e:
                logger.warning(f"Callback: video generation error: {e}")

    except Exception as e:
        logger.error(f"Callback: error sending results to user: {e}")


async def _deliver_error_to_user(bot, gen: dict, error_msg: str):
    """Send error notification to the user in Telegram (runs as background task)."""
    chat_id = gen["callback_chat_id"]
    status_msg_id = gen.get("callback_message_id")

    if status_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg_id,
                text=GENERATION_ERROR,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Callback: failed to edit error msg: {e}")
