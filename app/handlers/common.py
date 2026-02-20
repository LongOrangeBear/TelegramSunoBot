"""Common command handlers: /start, /help, /balance, profile, menu navigation."""

import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from app import database as db
from app.config import config
from app.keyboards import main_menu_kb, back_menu_kb
from app.texts import (
    WELCOME, WELCOME_BACK, HELP, PROFILE, BLOCKED,
)

router = Router()
logger = logging.getLogger(__name__)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = await db.get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    if user["is_blocked"]:
        await message.answer(BLOCKED, parse_mode="HTML")
        return

    if user["created_at"].date() == datetime.utcnow().date() and user["free_generations_left"] == config.free_credits_on_signup:
        # Brand new user
        text = WELCOME.format(free=config.free_credits_on_signup)
    else:
        total = user["credits"] + user["free_generations_left"]
        text = WELCOME_BACK.format(credits=total)

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=main_menu_kb(user["credits"], user["free_generations_left"]),
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP, parse_mode="HTML", reply_markup=back_menu_kb())


@router.message(Command("balance"))
async def cmd_balance(message: Message):
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Используйте /start для начала.")
        return
    total = user["credits"] + user["free_generations_left"]
    await message.answer(
        f"💎 Ваш баланс: <b>{total} кредитов</b>",
        parse_mode="HTML",
        reply_markup=back_menu_kb(),
    )


@router.message(Command("history"))
async def cmd_history(message: Message):
    from app.handlers.generation import show_history
    await show_history(message)


@router.message(Command("buy"))
async def cmd_buy(message: Message):
    from app.handlers.payments import show_buy_menu
    await show_buy_menu(message)


@router.message(Command("create"))
async def cmd_create(message: Message, state: FSMContext):
    from app.handlers.generation import start_creation
    await start_creation(message, state)


# ─── Callback: back to menu ───

@router.callback_query(F.data == "back_menu")
async def cb_back_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Используйте /start")
        return
    total = user["credits"] + user["free_generations_left"]
    await callback.message.edit_text(
        WELCOME_BACK.format(credits=total),
        parse_mode="HTML",
        reply_markup=main_menu_kb(user["credits"], user["free_generations_left"]),
    )
    await callback.answer()


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery):
    await callback.message.edit_text(HELP, parse_mode="HTML", reply_markup=back_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Используйте /start")
        return
    gens = await db.get_user_generations(callback.from_user.id, limit=1000)
    text = PROFILE.format(
        credits=user["credits"],
        free=user["free_generations_left"],
        tracks=len(gens),
        since=user["created_at"].strftime("%d.%m.%Y"),
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_menu_kb())
    await callback.answer()
