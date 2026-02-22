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
    mode_kb, gender_kb, style_kb, track_kb, history_track_kb, after_generation_kb,
    main_reply_kb,
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
    RATING_THANKS,
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

    today_count = await db.count_user_generations_today(user_id)
    if today_count >= config.max_generations_per_user_per_day:
        return RATE_LIMIT_USER.format(limit=config.max_generations_per_user_per_day)

    hour_count = await db.count_generations_last_hour()
    if hour_count >= config.max_generations_per_hour:
        return RATE_LIMIT_GLOBAL

    return None


async def check_credits(user_id: int) -> tuple[bool, dict]:
    """Check if user has credits (paid or free). Returns (has_credits, user)."""
    from datetime import datetime, timedelta
    user = await db.get_user(user_id)

    has_free = user["free_generations_left"] > 0
    if has_free and config.min_account_age_hours > 0:
        account_age = datetime.now() - user["created_at"]
        min_age = timedelta(hours=config.min_account_age_hours)
        if account_age < min_age:
            has_free = False

    if has_free and config.min_telegram_user_id > 0:
        if user_id > config.min_telegram_user_id:
            has_free = False

    has = (user["credits"] > 0 or has_free)
    return has, user


# ─── Start creation flow ───

async def start_creation(message_or_cb, state: FSMContext):
    """Entry point for creation flow — shows mode selection (idea / lyrics)."""
    user_id = message_or_cb.from_user.id

    # Rate limits
    error = await check_limits(user_id)
    if error:
        if isinstance(message_or_cb, CallbackQuery):
            await message_or_cb.message.answer(error, parse_mode="HTML")
            await message_or_cb.answer()
        else:
            await message_or_cb.answer(error, parse_mode="HTML")
        return

    # Credits check
    has_credits, user = await check_credits(user_id)
    if not has_credits:
        total = user["credits"] + user["free_generations_left"]
        text = NO_CREDITS.format(credits=total)
        if isinstance(message_or_cb, CallbackQuery):
            await message_or_cb.message.answer(text, parse_mode="HTML")
            await message_or_cb.answer()
        else:
            await message_or_cb.answer(text, parse_mode="HTML")
        return

    # Show mode selection (idea / lyrics)
    await state.set_state(GenerationStates.choosing_mode)
    if isinstance(message_or_cb, CallbackQuery):
        await message_or_cb.message.answer(CHOOSE_MODE, parse_mode="HTML", reply_markup=mode_kb())
        await message_or_cb.answer()
    else:
        await message_or_cb.answer(CHOOSE_MODE, parse_mode="HTML", reply_markup=mode_kb())


@router.callback_query(F.data == "create")
async def cb_create(callback: CallbackQuery, state: FSMContext):
    await start_creation(callback, state)


# ─── Mode selection (idea / lyrics) ───

@router.callback_query(F.data.startswith("mode:"))
async def cb_mode(callback: CallbackQuery, state: FSMContext):
    mode = callback.data.split(":")[1]

    if mode == "lyrics":
        await state.update_data(mode="lyrics")
    else:
        await state.update_data(mode="description")

    # Both modes go through gender → style → text input
    await state.set_state(GenerationStates.choosing_gender)
    await callback.message.edit_text(CHOOSE_GENDER, parse_mode="HTML", reply_markup=gender_kb())
    await callback.answer()


@router.callback_query(F.data == "back_mode")
async def cb_back_mode(callback: CallbackQuery, state: FSMContext):
    """Back to mode selection."""
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
    await state.set_state(GenerationStates.choosing_gender)
    await callback.message.edit_text(CHOOSE_GENDER, parse_mode="HTML", reply_markup=gender_kb())
    await callback.answer()


# ─── Style selection ───

@router.callback_query(F.data.startswith("style:"))
async def cb_style(callback: CallbackQuery, state: FSMContext):
    style = callback.data.split(":", 1)[1]

    if style == "custom_style":
        await state.set_state(GenerationStates.entering_custom_style)
        await callback.message.edit_text(ENTER_CUSTOM_STYLE, parse_mode="HTML")
        await callback.answer()
        return

    await state.update_data(style=style)
    data = await state.get_data()
    await state.set_state(GenerationStates.entering_prompt)
    # Show mode-appropriate prompt
    text = ENTER_LYRICS if data.get("mode") == "lyrics" else ENTER_PROMPT
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()


@router.message(GenerationStates.entering_custom_style)
async def on_custom_style(message: Message, state: FSMContext):
    custom_style = message.text.strip()[:90]
    await state.update_data(style=custom_style)
    data = await state.get_data()
    await state.set_state(GenerationStates.entering_prompt)
    # Show mode-appropriate prompt
    text = ENTER_LYRICS if data.get("mode") == "lyrics" else ENTER_PROMPT
    await message.answer(text, parse_mode="HTML")


# ─── Text input ───

@router.message(GenerationStates.entering_prompt)
async def on_prompt(message: Message, state: FSMContext):
    data = await state.get_data()
    mode = data.get("mode", "description")
    text = message.text.strip()

    # For description mode, limit to 400 chars
    if mode != "lyrics":
        text = text[:400]

    await state.update_data(prompt=text)
    await do_generate(message, state)


# ─── Generation ───

async def do_generate(message: Message, state: FSMContext):
    """Execute the generation after all inputs collected."""
    data = await state.get_data()
    user_id = message.from_user.id
    mode = data.get("mode", "description")
    style = data.get("style", "")
    voice_gender = data.get("voice_gender")
    prompt = data.get("prompt", "")

    # Final credit check
    has_credits, user = await check_credits(user_id)
    if not has_credits:
        await message.answer(
            NO_CREDITS.format(credits=user["credits"]),
            parse_mode="HTML",
        )
        await state.clear()
        return

    await state.set_state(GenerationStates.generating)

    if mode == "lyrics":
        status_text = (
            "🎵 Отлично! Создаю музыку по твоим стихам...\n"
            "Мне нужно несколько минут."
        )
    else:
        status_text = (
            "🎵 Отлично! Работаю над стихами и мелодией по твоей идее...\n"
            "Мне нужно несколько минут."
        )

    status_msg = await message.answer(
        status_text,
        parse_mode="HTML",
        reply_markup=main_reply_kb(),
    )

    gen_id = await db.create_generation(
        user_id=user_id,
        prompt=prompt,
        style=style,
        voice_gender=voice_gender,
        mode=mode,
    )

    try:
        client = get_suno_client()

        # For lyrics mode: use custom mode and pass user's text as lyrics
        if mode == "lyrics":
            result = await client.generate(
                prompt=prompt,
                style=style,
                voice_gender=voice_gender,
                mode="custom",
                lyrics=prompt,
                instrumental=False,
            )
        else:
            # Description mode: non-custom, build single prompt
            # Format: "{gender} vocal, {style}. песня на русском языке. {description}"
            parts = []
            if voice_gender:
                parts.append(f"{voice_gender} vocal")
            if style:
                parts.append(style)
            if config.russian_language_prefix:
                parts.append("песня на русском языке")
            parts.append(prompt)
            api_prompt = ". ".join(parts)

            result = await client.generate(
                prompt=api_prompt,
                mode="description",
                instrumental=False,
            )

        task_id = result["task_id"]
        await db.update_generation_status(gen_id, "processing", suno_song_ids=[task_id])

        if config.callback_base_url:
            await db.update_generation_callback_info(
                gen_id, message.chat.id, status_msg.message_id
            )
            logger.info(f"Generation {gen_id} submitted with callback, task_id={task_id}")
            await state.clear()
            return

        songs = await client.wait_for_completion(task_id)

        audio_urls = []
        image_urls = []
        song_titles = []
        song_ids = []
        for s in songs:
            url = s.get("audioUrl") or s.get("streamAudioUrl", "")
            audio_urls.append(url)
            image_urls.append(s.get("imageUrl") or s.get("image_url", ""))
            song_titles.append(s.get("title", f"AI Melody Track"))
            song_ids.append(s.get("id", ""))

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

        # Delete status message
        try:
            await status_msg.delete()
        except Exception:
            pass

        # SoNata-style delivery: per track — image, then audio with buttons
        for i, url in enumerate(audio_urls[:2]):
            if not url:
                continue
            try:
                # Send cover image if available
                img_url = image_urls[i] if i < len(image_urls) else ""
                title = song_titles[i] if i < len(song_titles) else f"Вариант {i+1}"
                if img_url:
                    try:
                        await message.answer_photo(
                            photo=img_url,
                            caption=f"🎵 Обложка для трека: <b>{title}</b>",
                            parse_mode="HTML",
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send cover image {i}: {e}")

                # Send audio file with track keyboard
                async with httpx.AsyncClient() as http:
                    resp = await http.get(url, timeout=60.0)
                    resp.raise_for_status()
                    audio_data = resp.content

                audio_file = BufferedInputFile(
                    audio_data,
                    filename=f"{title}.mp3",
                )
                await message.answer_audio(
                    audio_file,
                    title=title,
                    performer="AI Melody",
                    reply_markup=track_kb(gen_id, i),
                )
            except Exception as e:
                logger.error(f"Failed to send track {i}: {e}")

        # Send after-generation keyboard
        await message.answer(
            GENERATION_COMPLETE,
            parse_mode="HTML",
            reply_markup=after_generation_kb(gen_id),
        )

        # Video generation (if enabled)
        logger.info(f"Video check: enabled={config.video_generation_enabled}, song_ids={song_ids}, task_id={task_id}")
        if config.video_generation_enabled:
            for i, url in enumerate(audio_urls[:2]):
                if not url or not song_ids[i]:
                    continue
                try:
                    title = song_titles[i] if i < len(song_titles) else f"Вариант {i+1}"
                    video_result = await client.generate_video(task_id, song_ids[i])
                    video_url = await client.wait_for_video(video_result["task_id"])
                    await message.answer_video(
                        video=video_url,
                        caption=f"🎬 Видеоклип: <b>{title}</b>",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.warning(f"Video generation failed for track {i}: {e}")

    except ContentPolicyError:
        count = await db.increment_content_violations(user_id)
        await db.update_generation_status(gen_id, "error", error_message="content_policy")
        try:
            await status_msg.edit_text(
                CONTENT_VIOLATION.format(count=count),
                parse_mode="HTML",
            )
        except Exception:
            pass

    except SunoApiError as e:
        logger.error(f"Suno API error for gen {gen_id}: {e}")
        await db.update_generation_status(gen_id, "error", error_message=str(e))
        try:
            await status_msg.edit_text(GENERATION_ERROR, parse_mode="HTML")
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Unexpected error for gen {gen_id}: {e}", exc_info=True)
        await db.update_generation_status(gen_id, "error", error_message=str(e))
        try:
            await status_msg.edit_text(GENERATION_ERROR, parse_mode="HTML")
        except Exception:
            pass

    finally:
        await state.clear()


# ─── Rating ───

@router.callback_query(F.data.startswith("rate:"))
async def cb_rate(callback: CallbackQuery):
    """Save user's rating for a generation."""
    parts = callback.data.split(":")
    gen_id = int(parts[1])
    rating = int(parts[2])

    if rating < 1 or rating > 5:
        await callback.answer("Некорректная оценка", show_alert=True)
        return

    gen = await db.get_generation(gen_id)
    if not gen:
        await callback.answer("Генерация не найдена", show_alert=True)
        return

    if gen["user_id"] != callback.from_user.id:
        await callback.answer("Это не ваша генерация", show_alert=True)
        return

    await db.update_generation_rating(gen_id, rating)

    # Remove rating buttons — replace with "rated" confirmation
    try:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton

        builder = InlineKeyboardBuilder()
        # Keep the share button from the original keyboard
        if callback.message.reply_markup:
            for row in callback.message.reply_markup.inline_keyboard:
                for btn in row:
                    if btn.switch_inline_query is not None:
                        builder.row(btn)
                        break
        # Replace rating row with a confirmed rating indicator
        builder.row(
            InlineKeyboardButton(text=f"⭐ Ваша оценка: {rating}/5", callback_data="noop")
        )
        await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    except Exception as e:
        logger.warning(f"Failed to update rating keyboard: {e}")

    await callback.answer(f"⭐ Оценка {rating}/5 сохранена!")


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

    if user["credits"] <= 0 and user["free_generations_left"] <= 0:
        await callback.answer(
            f"🎵 Для скачивания нужен 1 балл. Баланс: {user['credits']}",
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

    if user["free_generations_left"] > 0:
        await db.use_free_generation(callback.from_user.id)
    else:
        await db.update_user_credits(callback.from_user.id, -1)

    try:
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

    await state.update_data(
        mode=gen["mode"],
        style=gen.get("style", ""),
        voice_gender=gen.get("voice_gender"),
        prompt=gen.get("prompt", ""),
    )

    await callback.answer("⚡ Запускаю новую генерацию...")
    msg = await callback.message.answer(GENERATING, parse_mode="HTML")

    user_id = callback.from_user.id
    has_credits, user = await check_credits(user_id)
    if not has_credits:
        await msg.edit_text(
            NO_CREDITS.format(credits=user["credits"]),
            parse_mode="HTML",
        )
        return

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

        regen_mode = data.get("mode", "description")
        if regen_mode == "lyrics":
            result = await client.generate(
                prompt=data.get("prompt", ""),
                style=data.get("style", ""),
                voice_gender=data.get("voice_gender"),
                mode="custom",
                lyrics=data.get("prompt", ""),
                instrumental=False,
            )
        else:
            # Description mode: non-custom, build single prompt
            parts = []
            regen_gender = data.get("voice_gender")
            regen_style = data.get("style", "")
            if regen_gender:
                parts.append(f"{regen_gender} vocal")
            if regen_style:
                parts.append(regen_style)
            if config.russian_language_prefix:
                parts.append("песня на русском языке")
            parts.append(data.get("prompt", ""))
            api_prompt = ". ".join(parts)

            result = await client.generate(
                prompt=api_prompt,
                mode="description",
                instrumental=False,
            )

        task_id = result["task_id"]
        await db.update_generation_status(gen_id_new, "processing", suno_song_ids=[task_id])

        if config.callback_base_url:
            await db.update_generation_callback_info(
                gen_id_new, callback.message.chat.id, msg.message_id
            )
            logger.info(f"Regen {gen_id_new} submitted with callback, task_id={task_id}")
            await state.clear()
            return

        songs = await client.wait_for_completion(task_id)

        audio_urls = []
        image_urls = []
        song_titles = []
        song_ids = []
        for s in songs:
            url = s.get("audioUrl") or s.get("streamAudioUrl", "")
            audio_urls.append(url)
            image_urls.append(s.get("imageUrl") or s.get("image_url", ""))
            song_titles.append(s.get("title", f"AI Melody Track"))
            song_ids.append(s.get("id", ""))

        if user["free_generations_left"] > 0:
            await db.use_free_generation(user_id)
        else:
            await db.update_user_credits(user_id, -1)

        await db.update_last_generation(user_id)
        await db.update_generation_status(gen_id_new, "complete", audio_urls=audio_urls, credits_spent=1)

        # Delete status message
        try:
            await msg.delete()
        except Exception:
            pass

        # SoNata-style delivery: per track — image, then audio with buttons
        for i, url in enumerate(audio_urls[:2]):
            if not url:
                continue
            try:
                img_url = image_urls[i] if i < len(image_urls) else ""
                title = song_titles[i] if i < len(song_titles) else f"Вариант {i+1}"
                if img_url:
                    try:
                        await callback.message.answer_photo(
                            photo=img_url,
                            caption=f"🎵 Обложка для трека: <b>{title}</b>",
                            parse_mode="HTML",
                        )
                    except Exception as e:
                        logger.warning(f"Regen: failed to send cover image {i}: {e}")

                async with httpx.AsyncClient() as http:
                    resp = await http.get(url, timeout=60.0)
                    resp.raise_for_status()
                    audio_data = resp.content

                audio_file = BufferedInputFile(
                    audio_data,
                    filename=f"{title}.mp3",
                )
                await callback.message.answer_audio(
                    audio_file,
                    title=title,
                    performer="AI Melody",
                    reply_markup=track_kb(gen_id_new, i),
                )
            except Exception as e:
                logger.error(f"Regen track send error {i}: {e}")

        await callback.message.answer(
            GENERATION_COMPLETE,
            parse_mode="HTML",
            reply_markup=after_generation_kb(gen_id_new),
        )

        # Video generation (if enabled)
        logger.info(f"Regen video check: enabled={config.video_generation_enabled}, song_ids={song_ids}, task_id={task_id}")
        if config.video_generation_enabled:
            for i, url in enumerate(audio_urls[:2]):
                if not url or not song_ids[i]:
                    continue
                try:
                    title = song_titles[i] if i < len(song_titles) else f"Вариант {i+1}"
                    video_result = await client.generate_video(task_id, song_ids[i])
                    video_url = await client.wait_for_video(video_result["task_id"])
                    await callback.message.answer_video(
                        video=video_url,
                        caption=f"🎬 Видеоклип: <b>{title}</b>",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.warning(f"Regen video generation failed for track {i}: {e}")

    except ContentPolicyError:
        count = await db.increment_content_violations(user_id)
        await db.update_generation_status(gen_id_new, "error", error_message="content_policy")
        try:
            await msg.edit_text(
                CONTENT_VIOLATION.format(count=count),
                parse_mode="HTML",
            )
        except Exception:
            pass
    except SunoApiError as e:
        logger.error(f"Regen API error: {e}")
        await db.update_generation_status(gen_id_new, "error", error_message=str(e))
        try:
            await msg.edit_text(GENERATION_ERROR, parse_mode="HTML")
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Regen unexpected error: {e}", exc_info=True)
        try:
            await msg.edit_text(GENERATION_ERROR, parse_mode="HTML")
        except Exception:
            pass
    finally:
        await state.clear()


# ─── History ───

async def show_history(message: Message):
    gens = await db.get_user_generations(message.from_user.id, limit=10)
    if not gens:
        await message.answer(HISTORY_EMPTY, parse_mode="HTML")
        return

    total = len(gens)
    await message.answer(
        f"📚 <b>Ваши треки</b> (последние {total}):",
        parse_mode="HTML",
    )

    for i, g in enumerate(gens):
        gen_id = g["id"]
        date = g["created_at"].strftime("%d.%m.%Y %H:%M")
        style = g.get("style", "—")
        prompt = g.get("prompt", "")
        prompt_short = (prompt[:60] + "...") if len(prompt) > 60 else prompt
        rating = f"  ⭐ {g['rating']}/5" if g.get("rating") else ""
        mode_label = "📝 Стихи" if g.get("mode") == "lyrics" else "💡 Идея"

        caption = (
            f"🎵 <b>{prompt_short}</b>\n"
            f"{mode_label} • 🎼 {style}{rating}\n"
            f"📅 {date}"
        )

        audio_urls = g.get("audio_urls") or []
        sent_audio = False

        for idx, url in enumerate(audio_urls[:2]):
            if not url:
                continue
            try:
                async with httpx.AsyncClient() as http:
                    resp = await http.get(url, timeout=30.0)
                    resp.raise_for_status()
                    audio_data = resp.content

                title = (prompt[:50] or f"Трек {i+1}") + (f" (вар. {idx+1})" if len(audio_urls) > 1 else "")
                audio_file = BufferedInputFile(
                    audio_data,
                    filename=f"{title}.mp3",
                )
                await message.answer_audio(
                    audio_file,
                    caption=caption if idx == 0 else None,
                    parse_mode="HTML",
                    title=title,
                    performer="AI Melody",
                    reply_markup=history_track_kb(gen_id, idx),
                )
                sent_audio = True
            except Exception as e:
                logger.warning(f"History: failed to send audio {gen_id}/{idx}: {e}")

        # Fallback: text-only if audio not available
        if not sent_audio:
            await message.answer(caption, parse_mode="HTML")


@router.callback_query(F.data == "history")
async def cb_history(callback: CallbackQuery):
    await callback.answer()
    await show_history(callback.message)
