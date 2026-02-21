"""Callback endpoint for receiving Suno API results from KIE.ai."""

import logging

from aiohttp import web

from app import database as db
from app.keyboards import result_kb, back_menu_kb
from app.texts import GENERATION_COMPLETE, GENERATION_ERROR

logger = logging.getLogger(__name__)


async def handle_suno_callback(request: web.Request) -> web.Response:
    """
    Receive callback POST from KIE.ai when a generation task finishes.

    Expected payload:
    {
        "code": 200,
        "msg": "success",
        "data": {
            "taskId": "...",
            "callbackType": "complete",
            "data": [
                {
                    "id": "...",
                    "audioUrl": "https://...",
                    "streamAudioUrl": "https://...",
                    "title": "...",
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

    logger.info(f"Suno callback received: code={payload.get('code')}")

    code = payload.get("code")
    data = payload.get("data", {})
    task_id = data.get("taskId", "")

    if not task_id:
        logger.warning(f"Callback: no taskId in payload: {payload}")
        return web.json_response({"status": "ok"})

    # Find generation by task_id (stored in suno_song_ids)
    gen = await db.get_generation_by_task_id(task_id)
    if not gen:
        logger.warning(f"Callback: generation not found for task_id={task_id}")
        return web.json_response({"status": "ok"})

    gen_id = gen["id"]
    user_id = gen["user_id"]

    # Get bot instance from app context
    get_bot = request.app.get("get_bot")
    bot = get_bot() if get_bot else None

    if code == 200:
        # Success — extract audio URLs
        callback_type = data.get("callbackType", "")
        suno_data = data.get("data", [])

        if not suno_data:
            # Sometimes data comes in response.sunoData format
            response_obj = data.get("response", {})
            suno_data = response_obj.get("sunoData", [])

        audio_urls = []
        for s in suno_data:
            url = s.get("audioUrl") or s.get("streamAudioUrl") or s.get("audio_url", "")
            audio_urls.append(url)

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

        # Send result to user via bot
        if bot and gen.get("callback_chat_id"):
            chat_id = gen["callback_chat_id"]
            status_msg_id = gen.get("callback_message_id")

            try:
                from aiogram.types import URLInputFile

                # Send voice previews
                for i, url in enumerate(audio_urls[:2]):
                    if url:
                        try:
                            voice = URLInputFile(url, filename=f"preview_{i+1}.ogg")
                            await bot.send_voice(
                                chat_id=chat_id,
                                voice=voice,
                                caption=f"🔊 Вариант {i+1}",
                            )
                        except Exception as e:
                            logger.error(f"Callback: failed to send voice {i}: {e}")

                # Update status message
                if status_msg_id:
                    try:
                        await bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=status_msg_id,
                            text=GENERATION_COMPLETE,
                            parse_mode="HTML",
                            reply_markup=result_kb(gen_id),
                        )
                    except Exception as e:
                        logger.error(f"Callback: failed to edit status msg: {e}")
            except Exception as e:
                logger.error(f"Callback: error sending results to user: {e}")

        logger.info(f"Callback: generation {gen_id} completed with {len(audio_urls)} tracks")

    else:
        # Error
        error_msg = payload.get("msg", "Unknown error")
        await db.update_generation_status(gen_id, "error", error_message=error_msg)

        if bot and gen.get("callback_chat_id"):
            chat_id = gen["callback_chat_id"]
            status_msg_id = gen.get("callback_message_id")
            if status_msg_id:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=status_msg_id,
                        text=GENERATION_ERROR,
                        parse_mode="HTML",
                        reply_markup=back_menu_kb(),
                    )
                except Exception as e:
                    logger.error(f"Callback: failed to edit error msg: {e}")

        logger.warning(f"Callback: generation {gen_id} failed: {error_msg}")

    return web.json_response({"status": "ok"})
