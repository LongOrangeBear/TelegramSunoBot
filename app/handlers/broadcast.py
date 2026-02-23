"""Broadcast handler — allows admins to send messages to all users."""

import asyncio
import logging

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app import database as db
from app.config import config

router = Router()
logger = logging.getLogger(__name__)


class BroadcastStates(StatesGroup):
    awaiting_message = State()


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    """Start broadcast flow — admin only."""
    if message.from_user.id not in config.admin_ids:
        return  # silently ignore for non-admins

    await state.set_state(BroadcastStates.awaiting_message)
    await message.answer(
        "📢 <b>Рассылка</b>\n\n"
        "Отправьте сообщение, которое нужно разослать всем пользователям.\n"
        "Поддерживается:\n"
        "• Текст (с HTML-разметкой)\n"
        "• Фото + подпись\n"
        "• Просто фото\n\n"
        "Для отмены — /cancel",
        parse_mode="HTML",
    )


@router.message(Command("cancel"), BroadcastStates.awaiting_message)
async def cmd_cancel_broadcast(message: Message, state: FSMContext):
    """Cancel broadcast."""
    await state.clear()
    await message.answer("❌ Рассылка отменена.")


@router.message(BroadcastStates.awaiting_message)
async def on_broadcast_message(message: Message, state: FSMContext):
    """Receive broadcast content and send to all users."""
    if message.from_user.id not in config.admin_ids:
        await state.clear()
        return

    await state.clear()

    user_ids = await db.get_all_user_ids()
    total = len(user_ids)

    if total == 0:
        await message.answer("⚠️ Нет пользователей для рассылки.")
        return

    progress_msg = await message.answer(
        f"📢 Начинаю рассылку для <b>{total}</b> пользователей...",
        parse_mode="HTML",
    )

    sent = 0
    failed = 0
    blocked = 0

    for i, user_id in enumerate(user_ids):
        try:
            if message.photo:
                # Photo message (with optional caption)
                photo = message.photo[-1]  # best quality
                await message.bot.send_photo(
                    chat_id=user_id,
                    photo=photo.file_id,
                    caption=message.caption or "",
                    parse_mode="HTML",
                )
            elif message.text:
                # Text-only message
                await message.bot.send_message(
                    chat_id=user_id,
                    text=message.text,
                    parse_mode="HTML",
                )
            else:
                # Forward any other message type (video, document, etc.)
                await message.copy_to(chat_id=user_id)
            sent += 1
        except Exception as e:
            error_str = str(e).lower()
            if "blocked" in error_str or "deactivated" in error_str or "not found" in error_str:
                blocked += 1
                await db.mark_user_blocked(user_id)
            else:
                failed += 1
                logger.warning(f"Broadcast to {user_id} failed: {e}")

        # Rate limiting: ~25 msg/sec to stay under Telegram limit
        await asyncio.sleep(0.04)

        # Progress update every 50 users
        if (i + 1) % 50 == 0:
            try:
                await progress_msg.edit_text(
                    f"📢 Рассылка: <b>{i + 1}/{total}</b>\n"
                    f"✅ Доставлено: {sent}\n"
                    f"🚫 Заблокировали бота: {blocked}\n"
                    f"❌ Ошибки: {failed}",
                    parse_mode="HTML",
                )
            except Exception:
                pass

    # Final report
    try:
        await progress_msg.edit_text(
            f"📢 <b>Рассылка завершена!</b>\n\n"
            f"👥 Всего: {total}\n"
            f"✅ Доставлено: {sent}\n"
            f"🚫 Заблокировали бота: {blocked}\n"
            f"❌ Ошибки: {failed}",
            parse_mode="HTML",
        )
    except Exception:
        await message.answer(
            f"📢 Рассылка завершена: {sent}✅ / {blocked}🚫 / {failed}❌ из {total}",
        )

    logger.info(
        f"Broadcast by {message.from_user.id}: total={total} sent={sent} blocked={blocked} failed={failed}"
    )
