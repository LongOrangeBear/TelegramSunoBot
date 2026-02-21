"""Music generation flow handlers."""

import logging
from io import BytesIO

import httpx
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile, URLInputFile
from aiogram.fsm.context import FSMContext

from app import database as db
from app.config import config
from app.keyboards import (
    mode_kb, gender_kb, style_kb, result_kb,
    back_menu_kb, main_menu_kb,
)
from app.states import GenerationStates
from app.suno_api import get_suno_client, SunoApiError, ContentPolicyError
from app.texts import (
    CHOOSE_MODE, CHOOSE_GENDER, CHOOSE_STYLE,
    ENTER_PROMPT, ENTER_LYRICS, ENTER_CUSTOM_STYLE,
    GENERATING, GENERATION_COMPLETE, GENERATION_ERROR,
    CONTENT_VIOLATION, NO_CREDITS, BLOCKED,
    RATE_LIMIT_USER, RATE_LIMIT_GLOBAL,
    HISTORY_EMPTY, HISTORY_HEADER, DOWNLOAD_SUCCESS, DOWNLOAD_NO_CREDITS,
)

router = Router()
logger = logging.getLogger(__name__)


# ─── Rate limit checks ───

async def check_limits(user_id: int) -> str | None:
    """Returns error message if rate limited, None if OK."""
    user = await db.get_user(user_id)
    if not user:
        return "Используйте /start"
    if user["is_blocked"]:
        return BLOCKED

    # Check daily user limit
    today_count = await db.count_user_generations_today(user_id)
    if today_count >= config.max_generations_per_user_per_day:
        return RATE_LIMIT_USER.format(limit=config.max_generations_per_user_per_day)

    # Check hourly global limit
    hour_count = await db.count_generations_last_hour()
    if hour_count >= config.max_generations_per_hour:
        return RATE_LIMIT_GLOBAL

    return None


async def check_credits(user_id: int) -> tuple[bool, dict]:
    """Check if user has credits (paid or free). Returns (has_credits, user)."""
    from datetime import datetime, timedelta
    user = await db.get_user(user_id)

    # Account age check for free credits
    has_free = user["free_generations_left"] > 0
    if has_free and config.min_account_age_hours > 0:
        # Use datetime.now() to match PostgreSQL NOW() (both use server local time)
        account_age = datetime.now() - user["created_at"]
        min_age = timedelta(hours=config.min_account_age_hours)
        if account_age < min_age:
            # Too new in bot — only paid credits count
            has_free = False

    # Telegram account age check (higher ID = newer account)
    if has_free and config.min_telegram_user_id > 0:
        if user_id > config.min_telegram_user_id:
            # Suspiciously new Telegram account — block free credits
            has_free = False

    has = (user["credits"] > 0 or has_free)
    return has, user


# ─── Start creation flow ───

async def start_creation(message_or_cb, state: FSMContext):
    """Entry point for creation flow."""
    user_id = (
        message_or_cb.from_user.id
        if isinstance(message_or_cb, (Message, CallbackQuery))
        else message_or_cb.from_user.id
    )

    # Rate limits
    error = await check_limits(user_id)
    if error:
        if isinstance(message_or_cb, CallbackQuery):
            await message_or_cb.message.edit_text(error, parse_mode="HTML", reply_markup=back_menu_kb())
            await message_or_cb.answer()
        else:
            await message_or_cb.answer(error, parse_mode="HTML", reply_markup=back_menu_kb())
        return

    # Credits check
    has_credits, user = await check_credits(user_id)
    if not has_credits:
        total = user["credits"] + user["free_generations_left"]
        text = NO_CREDITS.format(credits=total)
        if isinstance(message_or_cb, CallbackQuery):
            from app.handlers.payments import show_buy_menu_edit
            await show_buy_menu_edit(message_or_cb, extra_text=text)
        else:
            await message_or_cb.answer(text, parse_mode="HTML", reply_markup=back_menu_kb())
        return

    await state.set_state(GenerationStates.choosing_mode)
    if isinstance(message_or_cb, CallbackQuery):
        await message_or_cb.message.edit_text(CHOOSE_MODE, parse_mode="HTML", reply_markup=mode_kb())
        await message_or_cb.answer()
    else:
        await message_or_cb.answer(CHOOSE_MODE, parse_mode="HTML", reply_markup=mode_kb())


@router.callback_query(F.data == "create")
async def cb_create(callback: CallbackQuery, state: FSMContext):
    await start_creation(callback, state)


# ─── Mode selection ───

@router.callback_query(F.data.startswith("mode:"))
async def cb_mode(callback: CallbackQuery, state: FSMContext):
    mode = callback.data.split(":")[1]
    await state.update_data(mode=mode)

    if mode == "instrumental":
        # Skip gender, go to style
        await state.set_state(GenerationStates.choosing_style)
        await callback.message.edit_text(CHOOSE_STYLE, parse_mode="HTML", reply_markup=style_kb())
    else:
        await state.set_state(GenerationStates.choosing_gender)
        await callback.message.edit_text(CHOOSE_GENDER, parse_mode="HTML", reply_markup=gender_kb())
    await callback.answer()


@router.callback_query(F.data == "back_mode")
async def cb_back_mode(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GenerationStates.choosing_mode)
    await callback.message.edit_text(CHOOSE_MODE, parse_mode="HTML", reply_markup=mode_kb())
    await callback.answer()


# ─── Gender selection ───

@router.callback_query(F.data.startswith("gender:"))
async def cb_gender(callback: CallbackQuery, state: FSMContext):
    gender = callback.data.split(":")[1]
    await state.update_data(voice_gender=gender)
    await state.set_state(GenerationStates.choosing_style)
    await callback.message.edit_text(CHOOSE_STYLE, parse_mode="HTML", reply_markup=style_kb())
    await callback.answer()


@router.callback_query(F.data == "back_gender")
async def cb_back_gender(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("mode") == "instrumental":
        await state.set_state(GenerationStates.choosing_mode)
        await callback.message.edit_text(CHOOSE_MODE, parse_mode="HTML", reply_markup=mode_kb())
    else:
        await state.set_state(GenerationStates.choosing_gender)
        await callback.message.edit_text(CHOOSE_GENDER, parse_mode="HTML", reply_markup=gender_kb())
    await callback.answer()


# ─── Style selection ───

@router.callback_query(F.data.startswith("style:"))
async def cb_style(callback: CallbackQuery, state: FSMContext):
    style = callback.data.split(":")[1]

    if style == "custom_style":
        await state.set_state(GenerationStates.entering_custom_style)
        await callback.message.edit_text(ENTER_CUSTOM_STYLE, parse_mode="HTML", reply_markup=back_menu_kb())
        await callback.answer()
        return

    await state.update_data(style=style)
    data = await state.get_data()

    if data.get("mode") == "custom":
        await state.set_state(GenerationStates.entering_lyrics)
        await callback.message.edit_text(ENTER_LYRICS, parse_mode="HTML", reply_markup=back_menu_kb())
    else:
        await state.set_state(GenerationStates.entering_prompt)
        await callback.message.edit_text(ENTER_PROMPT, parse_mode="HTML", reply_markup=back_menu_kb())
    await callback.answer()


@router.message(GenerationStates.entering_custom_style)
async def on_custom_style(message: Message, state: FSMContext):
    await state.update_data(style=message.text.strip())
    data = await state.get_data()

    if data.get("mode") == "custom":
        await state.set_state(GenerationStates.entering_lyrics)
        await message.answer(ENTER_LYRICS, parse_mode="HTML", reply_markup=back_menu_kb())
    else:
        await state.set_state(GenerationStates.entering_prompt)
        await message.answer(ENTER_PROMPT, parse_mode="HTML", reply_markup=back_menu_kb())


# ─── Text input ───

@router.message(GenerationStates.entering_prompt)
async def on_prompt(message: Message, state: FSMContext):
    await state.update_data(prompt=message.text.strip())
    await do_generate(message, state)


@router.message(GenerationStates.entering_lyrics)
async def on_lyrics(message: Message, state: FSMContext):
    await state.update_data(lyrics=message.text.strip())
    # For custom mode, use lyrics as the main content, prompt is title
    await state.set_state(GenerationStates.entering_prompt)
    await message.answer(
        "📝 <b>Введите название песни:</b>",
        parse_mode="HTML",
        reply_markup=back_menu_kb(),
    )


# ─── Generation ───

async def do_generate(message: Message, state: FSMContext):
    """Execute the generation after all inputs collected."""
    data = await state.get_data()
    user_id = message.from_user.id
    mode = data.get("mode", "description")
    style = data.get("style", "")
    voice_gender = data.get("voice_gender")
    prompt = data.get("prompt", "")
    lyrics = data.get("lyrics")

    # Final credit check
    has_credits, user = await check_credits(user_id)
    if not has_credits:
        await message.answer(
            NO_CREDITS.format(credits=user["credits"]),
            parse_mode="HTML",
            reply_markup=back_menu_kb(),
        )
        await state.clear()
        return

    await state.set_state(GenerationStates.generating)
    status_msg = await message.answer(GENERATING, parse_mode="HTML")

    # Create DB record
    gen_id = await db.create_generation(
        user_id=user_id,
        prompt=prompt,
        style=style,
        voice_gender=voice_gender if mode != "instrumental" else None,
        mode=mode,
    )

    try:
        client = get_suno_client()

        # Call Suno v1 API
        result = await client.generate(
            prompt=prompt,
            style=style,
            voice_gender=voice_gender if mode != "instrumental" else None,
            mode=mode,
            lyrics=lyrics,
            instrumental=(mode == "instrumental"),
        )

        task_id = result["task_id"]
        await db.update_generation_status(gen_id, "processing", suno_song_ids=[task_id])

        # If callback is configured, store chat info and return (result will arrive via callback)
        if config.callback_base_url:
            await db.update_generation_callback_info(
                gen_id, message.chat.id, status_msg.message_id
            )
            logger.info(f"Generation {gen_id} submitted with callback, task_id={task_id}")
            await state.clear()
            return

        # Fallback: polling for completion
        songs = await client.wait_for_completion(task_id)

        # Extract audio URLs from sunoData (camelCase keys)
        audio_urls = []
        for s in songs:
            url = s.get("audioUrl") or s.get("streamAudioUrl") or s.get("audio_url", "")
            audio_urls.append(url)

        # Deduct credit
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

        # Send voice previews
        tg_file_ids = []
        for i, url in enumerate(audio_urls[:2]):
            if url:
                try:
                    voice = URLInputFile(url, filename=f"preview_{i+1}.ogg")
                    sent = await message.answer_voice(
                        voice,
                        caption=f"🔊 Вариант {i+1}",
                    )
                    tg_file_ids.append(sent.voice.file_id if sent.voice else "")
                except Exception as e:
                    logger.error(f"Failed to send voice {i}: {e}")
                    tg_file_ids.append("")

        await db.update_generation_status(gen_id, "complete", tg_file_ids=tg_file_ids)

        # Send result keyboard
        await status_msg.edit_text(
            GENERATION_COMPLETE,
            parse_mode="HTML",
            reply_markup=result_kb(gen_id),
        )

    except ContentPolicyError:
        count = await db.increment_content_violations(user_id)
        await db.update_generation_status(gen_id, "error", error_message="content_policy")
        await status_msg.edit_text(
            CONTENT_VIOLATION.format(count=count),
            parse_mode="HTML",
            reply_markup=back_menu_kb(),
        )

    except SunoApiError as e:
        logger.error(f"Suno API error for gen {gen_id}: {e}")
        await db.update_generation_status(gen_id, "error", error_message=str(e))
        await status_msg.edit_text(GENERATION_ERROR, parse_mode="HTML", reply_markup=back_menu_kb())

    except Exception as e:
        logger.error(f"Unexpected error for gen {gen_id}: {e}", exc_info=True)
        await db.update_generation_status(gen_id, "error", error_message=str(e))
        await status_msg.edit_text(GENERATION_ERROR, parse_mode="HTML", reply_markup=back_menu_kb())

    finally:
        await state.clear()


# ─── Result actions ───

@router.callback_query(F.data.startswith("listen:"))
async def cb_listen(callback: CallbackQuery):
    """Re-send voice preview."""
    parts = callback.data.split(":")
    gen_id = int(parts[1])
    idx = int(parts[2])

    gen = await db.get_generation(gen_id)
    if not gen or not gen.get("audio_urls"):
        await callback.answer("Трек не найден", show_alert=True)
        return

    urls = gen["audio_urls"]
    if idx >= len(urls) or not urls[idx]:
        await callback.answer("Трек недоступен", show_alert=True)
        return

    try:
        voice = URLInputFile(urls[idx], filename=f"preview_{idx+1}.ogg")
        await callback.message.answer_voice(voice, caption=f"🔊 Вариант {idx+1}")
    except Exception as e:
        logger.error(f"Listen error: {e}")
        await callback.answer("Ошибка воспроизведения", show_alert=True)
    await callback.answer()


@router.callback_query(F.data.startswith("download:"))
async def cb_download(callback: CallbackQuery):
    """Download MP3 for 1 credit."""
    parts = callback.data.split(":")
    gen_id = int(parts[1])
    idx = int(parts[2])

    user = await db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Используйте /start", show_alert=True)
        return

    # Check credits for download
    if user["credits"] <= 0 and user["free_generations_left"] <= 0:
        await callback.answer(
            f"💎 Для скачивания нужен 1 кредит. Баланс: {user['credits']}💎",
            show_alert=True,
        )
        return

    gen = await db.get_generation(gen_id)
    if not gen or not gen.get("audio_urls"):
        await callback.answer("Трек не найден", show_alert=True)
        return

    urls = gen["audio_urls"]
    if idx >= len(urls) or not urls[idx]:
        await callback.answer("Трек недоступен", show_alert=True)
        return

    # Deduct credit
    if user["free_generations_left"] > 0:
        await db.use_free_generation(callback.from_user.id)
    else:
        await db.update_user_credits(callback.from_user.id, -1)

    try:
        # Download and send as audio file
        async with httpx.AsyncClient() as http:
            resp = await http.get(urls[idx], timeout=60.0)
            resp.raise_for_status()
            audio_data = resp.content

        title = gen.get("prompt", "AI Melody Track")[:60]
        audio_file = BufferedInputFile(
            audio_data,
            filename=f"{title}.mp3",
        )
        await callback.message.answer_audio(
            audio_file,
            caption=DOWNLOAD_SUCCESS,
            title=title,
            performer="AI Melody",
        )
        await callback.answer("✅ Скачано!")
    except Exception as e:
        logger.error(f"Download error: {e}")
        # Refund credit on error
        await db.update_user_credits(callback.from_user.id, 1)
        await callback.answer("Ошибка скачивания. Кредит возвращён.", show_alert=True)


@router.callback_query(F.data.startswith("regenerate:"))
async def cb_regenerate(callback: CallbackQuery, state: FSMContext):
    """Regenerate with same params."""
    gen_id = int(callback.data.split(":")[1])
    gen = await db.get_generation(gen_id)
    if not gen:
        await callback.answer("Генерация не найдена", show_alert=True)
        return

    # Set state data from previous generation
    await state.update_data(
        mode=gen["mode"],
        style=gen.get("style", ""),
        voice_gender=gen.get("voice_gender"),
        prompt=gen.get("prompt", ""),
        lyrics=None,
    )

    # Fake message for do_generate (use callback message as proxy)
    await callback.answer("⚡ Запускаю новую генерацию...")
    msg = await callback.message.answer(GENERATING, parse_mode="HTML")

    # Re-run generation
    user_id = callback.from_user.id
    has_credits, user = await check_credits(user_id)
    if not has_credits:
        await msg.edit_text(
            NO_CREDITS.format(credits=user["credits"]),
            parse_mode="HTML",
            reply_markup=back_menu_kb(),
        )
        return

    # Use the regenerate path
    data = await state.get_data()
    gen_id_new = await db.create_generation(
        user_id=user_id,
        prompt=data.get("prompt", ""),
        style=data.get("style", ""),
        voice_gender=data.get("voice_gender"),
        mode=data.get("mode", "description"),
    )

    try:
        client = get_suno_client()
        result = await client.generate(
            prompt=data.get("prompt", ""),
            style=data.get("style", ""),
            voice_gender=data.get("voice_gender"),
            mode=data.get("mode", "description"),
            instrumental=(data.get("mode") == "instrumental"),
        )

        task_id = result["task_id"]
        await db.update_generation_status(gen_id_new, "processing", suno_song_ids=[task_id])

        # If callback is configured, store chat info and return
        if config.callback_base_url:
            await db.update_generation_callback_info(
                gen_id_new, callback.message.chat.id, msg.message_id
            )
            logger.info(f"Regen {gen_id_new} submitted with callback, task_id={task_id}")
            await state.clear()
            return

        # Fallback: polling
        songs = await client.wait_for_completion(task_id)

        audio_urls = []
        for s in songs:
            url = s.get("audioUrl") or s.get("streamAudioUrl") or s.get("audio_url", "")
            audio_urls.append(url)

        # Deduct credit
        if user["free_generations_left"] > 0:
            await db.use_free_generation(user_id)
        else:
            await db.update_user_credits(user_id, -1)

        await db.update_last_generation(user_id)
        await db.update_generation_status(gen_id_new, "complete", audio_urls=audio_urls, credits_spent=1)

        # Send voice previews
        for i, url in enumerate(audio_urls[:2]):
            if url:
                try:
                    voice = URLInputFile(url, filename=f"preview_{i+1}.ogg")
                    await callback.message.answer_voice(voice, caption=f"🔊 Вариант {i+1}")
                except Exception as e:
                    logger.error(f"Regen voice send error: {e}")

        await msg.edit_text(
            GENERATION_COMPLETE,
            parse_mode="HTML",
            reply_markup=result_kb(gen_id_new),
        )

    except ContentPolicyError:
        count = await db.increment_content_violations(user_id)
        await db.update_generation_status(gen_id_new, "error", error_message="content_policy")
        await msg.edit_text(
            CONTENT_VIOLATION.format(count=count),
            parse_mode="HTML",
            reply_markup=back_menu_kb(),
        )
    except SunoApiError as e:
        logger.error(f"Regen API error: {e}")
        await db.update_generation_status(gen_id_new, "error", error_message=str(e))
        await msg.edit_text(GENERATION_ERROR, parse_mode="HTML", reply_markup=back_menu_kb())
    except Exception as e:
        logger.error(f"Regen unexpected error: {e}", exc_info=True)
        await msg.edit_text(GENERATION_ERROR, parse_mode="HTML", reply_markup=back_menu_kb())
    finally:
        await state.clear()


# ─── History ───

async def show_history(message: Message):
    gens = await db.get_user_generations(message.from_user.id, limit=10)
    if not gens:
        await message.answer(HISTORY_EMPTY, parse_mode="HTML", reply_markup=back_menu_kb())
        return

    lines = [HISTORY_HEADER]
    for i, g in enumerate(gens, 1):
        date = g["created_at"].strftime("%d.%m %H:%M")
        style = g.get("style", "")
        prompt = (g.get("prompt", "")[:40] + "...") if len(g.get("prompt", "")) > 40 else g.get("prompt", "")
        lines.append(f"\n{i}. 🎵 <i>{prompt}</i>")
        lines.append(f"   📅 {date} | 🎼 {style}")

    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=back_menu_kb(),
    )


@router.callback_query(F.data == "history")
async def cb_history(callback: CallbackQuery):
    gens = await db.get_user_generations(callback.from_user.id, limit=10)
    if not gens:
        await callback.message.edit_text(HISTORY_EMPTY, parse_mode="HTML", reply_markup=back_menu_kb())
        await callback.answer()
        return

    lines = [HISTORY_HEADER]
    for i, g in enumerate(gens, 1):
        date = g["created_at"].strftime("%d.%m %H:%M")
        style = g.get("style", "")
        prompt = (g.get("prompt", "")[:40] + "...") if len(g.get("prompt", "")) > 40 else g.get("prompt", "")
        lines.append(f"\n{i}. 🎵 <i>{prompt}</i>")
        lines.append(f"   📅 {date} | 🎼 {style}")

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=back_menu_kb(),
    )
    await callback.answer()
