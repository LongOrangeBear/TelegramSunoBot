"""Telegram Stars + T-Bank payment handlers."""

import logging
import uuid

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, LabeledPrice,
    PreCheckoutQuery, InlineKeyboardMarkup, InlineKeyboardButton,
)

from app import database as db
from app.config import config
from app.keyboards import main_reply_kb, balance_kb, card_kb
from app.texts import (
    PAYMENT_SUCCESS, NO_CREDITS, BUY_CARD_HEADER,
    TBANK_PAYMENT_LINK, TBANK_PAYMENT_ERROR,
)

router = Router()
logger = logging.getLogger(__name__)


# ─── Telegram Stars flow ───

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


# ─── T-Bank card payment flow ───

@router.callback_query(F.data == "buy_card")
async def cb_buy_card(callback: CallbackQuery):
    """Show T-Bank card payment options."""
    await callback.message.edit_text(
        BUY_CARD_HEADER, parse_mode="HTML", reply_markup=card_kb()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy_tbank:"))
async def cb_buy_tbank(callback: CallbackQuery):
    """Initiate T-Bank payment — create order and send payment link."""
    from app import tbank_api

    parts = callback.data.split(":")
    credits = int(parts[1])
    amount_rub = int(parts[2])

    pkg = next(
        (p for p in config.credit_packages_rub if p["credits"] == credits),
        None,
    )
    if not pkg:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    user_id = callback.from_user.id
    order_id = f"tg_{user_id}_{uuid.uuid4().hex[:12]}"

    # Create pending payment in DB
    await db.create_tbank_payment(
        user_id=user_id,
        order_id=order_id,
        amount_rub=amount_rub,
        credits=credits,
    )

    # Build notification URL
    notification_url = None
    if config.callback_base_url:
        notification_url = f"{config.callback_base_url.rstrip('/')}/callback/tbank"

    try:
        result = await tbank_api.init_payment(
            amount_rub=amount_rub,
            order_id=order_id,
            description=f"AI Melody — {credits} баллов",
            notification_url=notification_url,
        )

        if not result.get("Success"):
            error_msg = result.get("Message", "Unknown error")
            logger.error(f"T-Bank Init failed: {error_msg} (code={result.get('ErrorCode')})")
            await callback.message.edit_text(
                TBANK_PAYMENT_ERROR, parse_mode="HTML", reply_markup=card_kb()
            )
            await callback.answer()
            return

        payment_url = result["PaymentURL"]
        tbank_payment_id = str(result.get("PaymentId", ""))

        # Update payment record with T-Bank payment ID
        if tbank_payment_id:
            async with db.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE payments SET tbank_payment_id = $2 WHERE order_id = $1",
                    order_id, tbank_payment_id,
                )

        # Send payment link to user
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy_card")],
        ])

        await callback.message.edit_text(
            TBANK_PAYMENT_LINK.format(credits=credits, rub=amount_rub),
            parse_mode="HTML",
            reply_markup=kb,
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"T-Bank payment error: {e}", exc_info=True)
        await callback.message.edit_text(
            TBANK_PAYMENT_ERROR, parse_mode="HTML", reply_markup=card_kb()
        )
        await callback.answer()
