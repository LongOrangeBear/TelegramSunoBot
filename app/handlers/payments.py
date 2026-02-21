"""Telegram Stars payment handlers."""

import logging

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, LabeledPrice,
    PreCheckoutQuery,
)

from app import database as db
from app.config import config
from app.keyboards import main_reply_kb, balance_kb
from app.texts import PAYMENT_SUCCESS, NO_CREDITS

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data.startswith("buy_credits:"))
async def cb_buy_credits(callback: CallbackQuery):
    """Send Telegram Stars invoice."""
    parts = callback.data.split(":")
    credits = int(parts[1])
    stars = int(parts[2])

    pkg = next(
        (p for p in config.credit_packages if p["credits"] == credits),
        None,
    )
    if not pkg:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    try:
        await callback.message.answer_invoice(
            title=f"⭐ Начисление {credits} баллов",
            description=f"⭐ Начисление {credits} баллов — ⭐ {stars}",
            payload=f"credits_{credits}_{stars}",
            currency="XTR",
            prices=[LabeledPrice(label=f"{credits} баллов", amount=stars)],
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

    await db.create_payment(
        user_id=message.from_user.id,
        tg_payment_id=payment.telegram_payment_charge_id,
        stars=stars,
        credits=credits,
    )

    user = await db.get_user(message.from_user.id)
    balance = user["credits"] + user["free_generations_left"]

    await message.answer(
        PAYMENT_SUCCESS.format(credits=credits, stars=stars, balance=balance),
        parse_mode="HTML",
        reply_markup=main_reply_kb(),
    )
    logger.info(
        f"Payment: user={message.from_user.id} credits={credits} stars={stars} "
        f"charge_id={payment.telegram_payment_charge_id}"
    )
