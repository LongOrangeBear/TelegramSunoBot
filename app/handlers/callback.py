"""Callback endpoint for receiving Suno API results."""

import asyncio
import logging

import httpx
from aiohttp import web

from app import database as db
from app.config import config
from app.keyboards import track_kb, after_generation_kb, preview_track_kb, preview_after_generation_kb
from app.suno_api import get_suno_client
from app.audio_preview import create_preview
from app.texts import (
    GENERATION_COMPLETE, GENERATION_ERROR,
    PREVIEW_CAPTION, PREVIEW_GENERATION_COMPLETE,
)

logger = logging.getLogger(__name__)

# In-memory store: video_task_id → {chat_id, title, bot_getter}
_pending_video_tasks: dict[str, dict] = {}


def register_video_task(video_task_id: str, chat_id: int, title: str, get_bot):
    """Register context for a pending video task so the callback can deliver it."""
    _pending_video_tasks[video_task_id] = {
        "chat_id": chat_id,
        "title": title,
        "get_bot": get_bot,
    }
    logger.info(f"Registered pending video task {video_task_id} for chat_id={chat_id}")


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

        # Deduct credit (free = preview only, paid = full MP3)
        user = await db.get_user(user_id)
        is_free = False
        if user:
            is_free = user["free_generations_left"] > 0
            if is_free:
                await db.use_free_generation(user_id)
                await db.log_balance_transaction(
                    user_id, -1, 'free_generation', f'Бесплатная генерация #{gen_id}',
                )
            else:
                await db.update_user_credits(user_id, -1)
                await db.log_balance_transaction(
                    user_id, -1, 'generation', f'Генерация #{gen_id}',
                )
            await db.update_last_generation(user_id)

        credits_spent = 0 if is_free else 1
        await db.update_generation_status(
            gen_id, "complete",
            audio_urls=audio_urls,
            credits_spent=credits_spent,
            song_titles=song_titles,
        )

        # For paid generations, mark as unlocked immediately
        if not is_free:
            await db.unlock_generation(gen_id)

        # Send result to user via bot asynchronously (don't block the 200 response)
        if bot and gen.get("callback_chat_id"):
            asyncio.create_task(
                _deliver_result_to_user(bot, gen, gen_id, audio_urls, image_urls, song_titles, song_ids, task_id, is_free)
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


async def handle_video_callback(request: web.Request) -> web.Response:
    """
    Receive callback POST from SunoAPI.org when a video (MP4) task finishes.

    Expected payload (per API docs):
    Success: {"code": 200, "msg": "MP4 generated successfully.", "data": {"task_id": "...", "video_url": "..."}}
    Failure: {"code": 400/451/500, "msg": "..."}
    """
    try:
        payload = await request.json()
    except Exception:
        logger.warning("Video callback: invalid JSON body")
        return web.json_response({"status": "error", "msg": "invalid json"}, status=400)

    code = payload.get("code")
    data = payload.get("data", {})
    task_id = data.get("task_id", "") if isinstance(data, dict) else ""
    msg = payload.get("msg", "")

    logger.info(f"Video callback received: code={code}, task_id={task_id}, msg={msg}, data={data}")

    if not task_id:
        logger.warning(f"Video callback: no task_id in payload: {payload}")
        return web.json_response({"status": "ok"})

    # Look up pending context
    ctx = _pending_video_tasks.pop(task_id, None)
    if not ctx:
        logger.warning(f"Video callback: no pending task for task_id={task_id}")
        return web.json_response({"status": "ok"})

    chat_id = ctx["chat_id"]
    title = ctx["title"]
    get_bot = ctx["get_bot"]
    bot = get_bot() if get_bot else None

    if code == 200:
        video_url = data.get("video_url", "")
        if video_url and bot:
            # Send video asynchronously (don't block the 200 response)
            asyncio.create_task(_deliver_video(bot, chat_id, video_url, title))
        elif not video_url:
            logger.warning(f"Video callback: success but no video_url in data: {data}")
    else:
        logger.warning(f"Video callback: failed for task_id={task_id}, code={code}, msg={msg}")

    return web.json_response({"status": "ok"})


async def _deliver_video(bot, chat_id: int, video_url: str, title: str):
    """Send a generated video to the user (runs as background task)."""
    try:
        await bot.send_video(
            chat_id=chat_id,
            video=video_url,
            caption=f"🎬 Видеоклип: <b>{title}</b>",
            parse_mode="HTML",
        )
        logger.info(f"Video delivered to chat_id={chat_id}: {title}")
    except Exception as e:
        logger.error(f"Video delivery failed for chat_id={chat_id}: {e}")


async def _deliver_result_to_user(
    bot, gen: dict, gen_id: int,
    audio_urls: list[str], image_urls: list[str], song_titles: list[str],
    song_ids: list[str] = None, original_task_id: str = "",
    is_free: bool = False,
):
    """Send generation results to the user in Telegram (runs as background task)."""
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

                # Download audio
                async with httpx.AsyncClient() as http:
                    resp = await http.get(url, timeout=60.0)
                    resp.raise_for_status()
                    audio_data = resp.content

                if is_free:
                    # ─── FREE: Send voice preview ───
                    try:
                        preview_data = await create_preview(audio_data)
                        voice_file = BufferedInputFile(
                            preview_data,
                            filename=f"preview_{i+1}.ogg",
                        )
                        await bot.send_voice(
                            chat_id=chat_id,
                            voice=voice_file,
                            caption=PREVIEW_CAPTION.format(title=title),
                            parse_mode="HTML",
                            reply_markup=preview_track_kb(gen_id, i),
                        )
                    except Exception as e:
                        logger.warning(f"Callback: preview creation failed for track {i}, sending full audio as fallback: {e}")
                        # Fallback: send full audio file
                        audio_file = BufferedInputFile(
                            audio_data,
                            filename=f"{title}.mp3",
                        )
                        await bot.send_audio(
                            chat_id=chat_id,
                            audio=audio_file,
                            title=f"🎧 {title}",
                            performer="AI Melody",
                            caption=PREVIEW_CAPTION.format(title=title),
                            parse_mode="HTML",
                            reply_markup=preview_track_kb(gen_id, i),
                        )
                else:
                    # ─── PAID: Send full MP3 ───
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
        if is_free:
            await bot.send_message(
                chat_id=chat_id,
                text=PREVIEW_GENERATION_COMPLETE,
                parse_mode="HTML",
                reply_markup=preview_after_generation_kb(gen_id),
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=GENERATION_COMPLETE,
                parse_mode="HTML",
                reply_markup=after_generation_kb(gen_id),
            )

        # Video generation (if enabled and PAID) — fire-and-forget
        if not is_free and config.video_generation_enabled and original_task_id and song_ids:
            logger.info(f"Callback video check: enabled={config.video_generation_enabled}, song_ids={song_ids}")
            try:
                client = get_suno_client()
                get_bot = lambda b=bot: b
                for i, url in enumerate(audio_urls[:2]):
                    if not url or i >= len(song_ids) or not song_ids[i]:
                        continue
                    try:
                        title = song_titles[i] if i < len(song_titles) else f"Вариант {i+1}"
                        video_result = await client.generate_video(original_task_id, song_ids[i])
                        video_task_id = video_result["task_id"]
                        register_video_task(video_task_id, chat_id, title, get_bot)
                    except Exception as e:
                        logger.warning(f"Callback: video generation request failed for track {i}: {e}")
            except Exception as e:
                logger.warning(f"Callback: video generation error: {e}")

    except Exception as e:
        logger.error(f"Callback: error sending results to user: {e}")


def _humanize_error(error_msg: str) -> str:
    """Convert raw Suno API error into a user-friendly Russian message."""
    if not error_msg:
        return GENERATION_ERROR

    lower = error_msg.lower()

    # Artist name detected in prompt/tags
    if "artist name" in lower:
        # Extract the artist name from the error if possible
        # e.g. "Your tags contain artist name maksim - we don't reference..."
        import re
        match = re.search(r'artist name\s+(\w+)', lower)
        name = match.group(1).title() if match else "исполнителя"
        return (
            f"❌ <b>Имя совпало с исполнителем</b>\n\n"
            f"В вашем тексте обнаружено имя «{name}», "
            f"которое совпало с именем известного исполнителя.\n\n"
            f"Нейросеть не может использовать имена реальных артистов. "
            f"Попробуйте изменить имя — например, используйте "
            f"уменьшительную форму или инициал.\n\n"
            f"Кредит не списан."
        )

    # Prompt too long
    if "prompt length" in lower or "cannot exceed" in lower or "too long" in lower:
        return (
            "❌ <b>Слишком длинный текст</b>\n\n"
            "Ваш текст превышает допустимый размер. "
            "Попробуйте сократить описание и отправить ещё раз.\n\n"
            "Кредит не списан."
        )

    # Title too long
    if "title" in lower and ("exceed" in lower or "length" in lower):
        return (
            "❌ <b>Слишком длинное название</b>\n\n"
            "Название трека превышает допустимый размер. "
            "Попробуйте сократить описание.\n\n"
            "Кредит не списан."
        )

    # Content policy / sensitive words
    if "sensitive" in lower or "content" in lower and ("violation" in lower or "policy" in lower or "moderation" in lower):
        return (
            "⚠️ <b>Контент отклонён</b>\n\n"
            "Ваш запрос содержит слова, которые не пропускает "
            "система модерации нейросети. Попробуйте переформулировать "
            "описание.\n\n"
            "Кредит не списан."
        )

    # Credits / balance
    if "credit" in lower and ("insufficient" in lower or "balance" in lower or "enough" in lower):
        return (
            "❌ <b>Ошибка на стороне сервиса</b>\n\n"
            "Произошла техническая ошибка при генерации. "
            "Мы уже работаем над решением. Попробуйте позже.\n\n"
            "Кредит не списан."
        )

    # Rate limited
    if "rate limit" in lower or "too many" in lower or "frequency" in lower:
        return (
            "⏰ <b>Слишком много запросов</b>\n\n"
            "Сервис временно перегружен. "
            "Подождите пару минут и попробуйте снова.\n\n"
            "Кредит не списан."
        )

    # Server / maintenance
    if "maintenance" in lower or "server error" in lower or "internal" in lower:
        return (
            "🔧 <b>Сервис временно недоступен</b>\n\n"
            "На стороне генерации музыки ведутся технические работы. "
            "Попробуйте через несколько минут.\n\n"
            "Кредит не списан."
        )

    # Permissions
    if "permission" in lower or "access" in lower:
        return (
            "❌ <b>Ошибка доступа</b>\n\n"
            "Произошла техническая ошибка. "
            "Мы уже работаем над решением. Попробуйте позже.\n\n"
            "Кредит не списан."
        )

    # Default fallback
    return GENERATION_ERROR


async def _deliver_error_to_user(bot, gen: dict, error_msg: str):
    """Send error notification to the user in Telegram (runs as background task)."""
    chat_id = gen["callback_chat_id"]
    status_msg_id = gen.get("callback_message_id")
    user_text = _humanize_error(error_msg)

    delivered = False
    if status_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg_id,
                text=user_text,
                parse_mode="HTML",
            )
            delivered = True
        except Exception as e:
            logger.warning(f"Callback: failed to edit error msg: {e}")

    if not delivered:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=user_text,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Callback: failed to send error msg to chat {chat_id}: {e}")
