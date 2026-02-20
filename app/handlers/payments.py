"""Telegram Stars payment handlers."""

import logging

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, LabeledPrice,
    PreCheckoutQuery,
)

from app import database as db
from app.config import config
from app.keyboards import buy_kb, back_menu_kb, main_menu_kb
from app.texts import BUY_HEADER, PAYMENT_SUCCESS, NO_CREDITS

router = Router()
logger = logging.getLogger(__name__)


async def show_buy_menu(message: Message):
    await message.answer(BUY_HEADER, parse_mode="HTML", reply_markup=buy_kb())


async def show_buy_menu_edit(callback: CallbackQuery, extra_text: str = ""):
    text = extra_text + "\n\n" + BUY_HEADER if extra_text else BUY_HEADER
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=buy_kb())
    await callback.answer()


@router.callback_query(F.data == "buy")
async def cb_buy(callback: CallbackQuery):
    await callback.message.edit_text(BUY_HEADER, parse_mode="HTML", reply_markup=buy_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("buy_credits:"))
async def cb_buy_credits(callback: CallbackQuery):
    """Send Telegram Stars invoice."""
    parts = callback.data.split(":")
    credits = int(parts[1])
    stars = int(parts[2])

    # Find matching package
    pkg = next(
        (p for p in config.credit_packages if p["credits"] == credits),
        None,
    )
    if not pkg:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    try:
        await callback.message.answer_invoice(
            title=f"{credits}💎 кредитов",
            description=f"Покупка {credits} кредитов для генерации музыки",
            payload=f"credits_{credits}_{stars}",
            currency="XTR",
            prices=[LabeledPrice(label=f"{credits} кредитов", amount=stars)],
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Invoice error: {e}")
        await callback.answer("Ошибка создания платежа", show_alert=True)


@router.pre_checkout_query()
async def on_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    """Approve all pre-checkout queries."""
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message):
    """Handle successful payment — add credits."""
    payment = message.successful_payment
    payload = payment.invoice_payload  # "credits_5_50"

    parts = payload.split("_")
    credits = int(parts[1])
    stars = int(parts[2])

    # Record payment and add credits
    await db.create_payment(
        user_id=message.from_user.id,
        tg_payment_id=payment.telegram_payment_charge_id,
        stars=stars,
        credits=credits,
    )

    user = await db.get_user(message.from_user.id)
    balance = user["credits"] + user["free_generations_left"]

    await message.answer(
        PAYMENT_SUCCESS.format(credits=credits, balance=balance),
        parse_mode="HTML",
        reply_markup=main_menu_kb(user["credits"], user["free_generations_left"]),
    )
    logger.info(
        f"Payment: user={message.from_user.id} credits={credits} stars={stars} "
        f"charge_id={payment.telegram_payment_charge_id}"
    )
