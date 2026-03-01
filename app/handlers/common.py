"""Common command handlers: /start, /help, /balance, profile, menu navigation."""

import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated
from aiogram.fsm.context import FSMContext

from app import database as db
from app.config import config
from app.keyboards import (
    main_reply_kb, balance_kb, stars_kb, mode_kb,
    BTN_CREATE, BTN_BALANCE, BTN_TRACKS, BTN_HELP,
)
from app.texts import (
    WELCOME, WELCOME_BACK, HELP, PROFILE, BLOCKED,
    INVITE, INVITE_INSTRUCTIONS, REFERRAL_BONUS,
    CHOOSE_MODE, BALANCE_PAGE, BUY_STARS_HEADER,
)

router = Router()
logger = logging.getLogger(__name__)


def is_blocked_error(e: Exception) -> bool:
    """Check if an exception indicates the user blocked the bot."""
    err = str(e).lower()
    return any(kw in err for kw in ("blocked", "deactivated", "not found", "chat not found",
                                     "user is deactivated", "bot was blocked"))


def _build_tariff_lines() -> str:
    """Build tariff text lines for balance page (Stars + RUB)."""
    lines = []
    stars = config.credit_packages
    rub = config.credit_packages_rub
    for i, pkg in enumerate(stars):
        rub_price = rub[i]["rub"] if i < len(rub) else "?"
        lines.append(f"🎵 {pkg['credits']}🎵 — ⭐{pkg['stars']} / {rub_price}₽")
    return "\n".join(lines)


# ─── /start ───

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    # Check for referral deep link: /start ref123456
    referred_by = None
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[1].startswith("ref"):
        try:
            referred_by = int(args[1][3:])
            if referred_by == message.from_user.id:
                referred_by = None
        except (ValueError, IndexError):
            referred_by = None

    existing_user = await db.get_user(message.from_user.id)
    is_new = existing_user is None

    user = await db.get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        referred_by=referred_by if is_new else None,
    )

    if user["is_blocked"]:
        await message.answer(BLOCKED, parse_mode="HTML")
        return

    # Give referral bonus to inviter (only for new users)
    if is_new and referred_by:
        try:
            referrer = await db.get_user(referred_by)
            if referrer:
                new_balance = await db.update_user_credits(referred_by, 1)
                await db.log_balance_transaction(
                    referred_by, 1, 'referral',
                    f'Реферал от {message.from_user.id}',
                )
                bot = message.bot
                await bot.send_message(
                    referred_by,
                    REFERRAL_BONUS.format(balance=new_balance),
                    parse_mode="HTML",
                )
                logger.info(f"Referral bonus: +1 credit to {referred_by} from {message.from_user.id}")
        except Exception as e:
            if is_blocked_error(e):
                await db.mark_user_blocked(referred_by)
                logger.info(f"Referral: inviter {referred_by} blocked the bot")
            else:
                logger.error(f"Failed to send referral bonus notification: {e}")

    if is_new:
        text = WELCOME.format(free=config.free_credits_on_signup)
        if config.free_credits_on_signup > 0:
            await db.log_balance_transaction(
                message.from_user.id, config.free_credits_on_signup,
                'signup_bonus', 'Бонус за регистрацию',
            )
    else:
        total = user["credits"] + user["free_generations_left"]
        text = WELCOME_BACK.format(credits=total)

    # Send with persistent Reply keyboard
    await message.answer(text, parse_mode="HTML", reply_markup=main_reply_kb())


# ─── Reply keyboard button handlers ───

@router.message(F.text == BTN_CREATE)
async def btn_create(message: Message, state: FSMContext):
    """Handle 'Создать песню' reply button."""
    from app.handlers.generation import start_creation
    await start_creation(message, state)


@router.message(F.text == BTN_BALANCE)
async def btn_balance(message: Message):
    """Handle 'Баланс' reply button."""
    await _show_balance(message, message.from_user.id)


async def _show_balance(message, user_id: int):
    """Reusable helper to show balance page. Can be called from other modules."""
    user = await db.get_user(user_id)
    if not user:
        await message.answer("Используйте /start для начала.", reply_markup=main_reply_kb())
        return
    free = user["free_generations_left"]
    if free > 0:
        free_line = f"🎁 Бесплатных: <b>{free}</b> (только превью 30 сек + обложки)\n"
    else:
        free_line = ""
    text = BALANCE_PAGE.format(
        credits=user["credits"],
        free_line=free_line,
        tariffs=_build_tariff_lines(),
    )
    await message.answer(text, parse_mode="HTML", reply_markup=balance_kb())


@router.message(F.text == BTN_TRACKS)
async def btn_tracks(message: Message):
    """Handle 'Мои треки' reply button."""
    from app.handlers.generation import show_history
    await show_history(message)


@router.message(F.text == BTN_HELP)
async def btn_help(message: Message):
    """Handle 'Помощь' reply button."""
    await message.answer(HELP, parse_mode="HTML")


# ─── Command shortcuts ───

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP, parse_mode="HTML")


@router.message(Command("balance"))
async def cmd_balance(message: Message):
    await _show_balance(message, message.from_user.id)


@router.message(Command("history"))
async def cmd_history(message: Message):
    from app.handlers.generation import show_history
    await show_history(message)


@router.message(Command("buy"))
async def cmd_buy(message: Message):
    await _show_balance(message, message.from_user.id)


@router.message(Command("create"))
async def cmd_create(message: Message, state: FSMContext):
    from app.handlers.generation import start_creation
    await start_creation(message, state)


# ─── Inline callbacks ───

@router.callback_query(F.data == "back_balance")
async def cb_back_balance(callback: CallbackQuery):
    """Back to balance page from Stars."""
    user = await db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Используйте /start")
        return
    free = user["free_generations_left"]
    free_line = f"🎁 Бесплатных: <b>{free}</b> (только превью 30 сек + обложки)\n" if free > 0 else ""
    text = BALANCE_PAGE.format(
        credits=user["credits"],
        free_line=free_line,
        tariffs=_build_tariff_lines(),
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=balance_kb())
    await callback.answer()


@router.callback_query(F.data == "buy_stars")
async def cb_buy_stars(callback: CallbackQuery):
    """Show Telegram Stars payment options."""
    await callback.message.edit_text(
        BUY_STARS_HEADER, parse_mode="HTML", reply_markup=stars_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery):
    await callback.message.edit_text(HELP, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    """No-op handler for label-only buttons."""
    await callback.answer()


@router.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Используйте /start")
        return
    gens = await db.get_user_generations(callback.from_user.id, limit=1000)
    referrals = await db.count_referrals(callback.from_user.id)
    text = PROFILE.format(
        credits=user["credits"],
        free=user["free_generations_left"],
        tracks=len(gens),
        referrals=referrals,
        since=user["created_at"].strftime("%d.%m.%Y"),
    )
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()


# ─── Invite / Share ───

@router.callback_query(F.data == "invite")
async def cb_invite(callback: CallbackQuery):
    """Send instructions + shareable message with bot link for forwarding."""
    bot_me = await callback.bot.get_me()
    bot_link = f"https://t.me/{bot_me.username}?start=ref{callback.from_user.id}"

    await callback.message.answer(
        INVITE_INSTRUCTIONS,
        parse_mode="HTML",
    )

    text = INVITE.format(bot_link=bot_link)
    await callback.message.answer(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer("📤 Перешлите сообщение ниже друзьям!")


# ─── my_chat_member — instant block/unblock detection ───

@router.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated):
    """Detect when a user blocks or unblocks the bot."""
    new_status = update.new_chat_member.status
    user_id = update.from_user.id

    if new_status in ("kicked", "left"):
        await db.mark_user_blocked(user_id)
        logger.info(f"User {user_id} blocked the bot (my_chat_member: {new_status})")
    elif new_status == "member":
        await db.mark_user_unblocked(user_id)
        logger.info(f"User {user_id} unblocked the bot (my_chat_member: {new_status})")
