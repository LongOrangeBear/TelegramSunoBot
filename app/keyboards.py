"""Keyboard builders for the bot — Reply keyboard + Inline keyboards."""

from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import config


# ─── Button text constants (used for matching in handlers) ───

BTN_CREATE = "🎵 Создать песню"
BTN_BALANCE = "💰 Баланс"
BTN_TRACKS = "📚 Мои треки"
BTN_HELP = "❓ Помощь"


# ─── Persistent Reply Keyboard (always visible) ───

def main_reply_kb() -> ReplyKeyboardMarkup:
    """Persistent bottom menu — 2x2 layout."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CREATE), KeyboardButton(text=BTN_BALANCE)],
            [KeyboardButton(text=BTN_TRACKS), KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


# ─── Mode selection (Есть идея / Есть стихи) ───

def mode_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💡 Есть идея", callback_data="mode:idea"),
    )
    builder.row(
        InlineKeyboardButton(text="📝 Есть стихи", callback_data="mode:lyrics"),
    )
    builder.row(
        InlineKeyboardButton(text="🎉 Поздравительная песня", callback_data="mode:greeting"),
    )
    return builder.as_markup()


# ─── Gender selection ───

def gender_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🚹 Мужской", callback_data="gender:male"),
        InlineKeyboardButton(text="🚺 Женский", callback_data="gender:female"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_mode"))
    return builder.as_markup()


# ─── Style selection ───

STYLES = [
    ("🎸 Рок", "rock"),
    ("🎹 Поп", "pop"),
    ("🎤 Рэп", "rap"),
    ("🎶 Хип-хоп", "hip-hop"),
    ("🎷 Джаз / Соул", "jazz soul"),
    ("🎻 Классика", "classical"),
    ("🔊 Электро", "electronic edm"),
    ("🎤 Шансон", "russian chanson"),
    ("💔 Баллада", "ballad"),
    ("🪗 Русская народная", "russian folk"),
    ("🎉 Праздничная", "holiday celebration"),
]


def style_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i in range(0, len(STYLES), 3):
        row = []
        for label, data in STYLES[i:i+3]:
            row.append(InlineKeyboardButton(text=label, callback_data=f"style:{data}"))
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="✏️ Свой стиль", callback_data="style:custom_style"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_gender"))
    return builder.as_markup()


# ─── Greeting wizard keyboards ───

GREETING_RECIPIENTS = [
    ("👩 Маме", "маме"),
    ("👨 Папе", "папе"),
    ("💕 Любимому/ой", "любимому человеку"),
    ("👫 Другу/подруге", "другу"),
    ("💼 Коллеге", "коллеге"),
    ("👶 Ребёнку", "ребёнку"),
    ("🎖 Мужчине (23 февраля)", "мужчине (защитнику)"),
]

GREETING_OCCASIONS = [
    ("🎂 День рождения", "bday"),
    ("🎖 23 февраля", "feb23"),
    ("🌷 8 марта", "mar8"),
    ("💒 Свадьба", "wedding"),
    ("🎊 Юбилей", "jubilee"),
    ("🎓 Выпускной", "grad"),
    ("🎄 Новый год", "newyear"),
]

GREETING_OCCASION_LABELS = {
    "bday": "День рождения",
    "feb23": "23 февраля — День защитника Отечества",
    "mar8": "8 марта — Международный женский день",
    "wedding": "Свадьба",
    "jubilee": "Юбилей",
    "grad": "Выпускной",
    "newyear": "Новый год",
}

GREETING_MOODS = [
    ("🎩 Серьёзное / трогательное", "serious"),
    ("😄 Шутливое / весёлое", "funny"),
    ("🎭 Микс", "mix"),
]

GREETING_MOOD_LABELS = {
    "serious": "трогательное и душевное",
    "funny": "шутливое и весёлое",
    "mix": "и смешное, и трогательное",
}


def greeting_recipient_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, data in GREETING_RECIPIENTS:
        builder.row(InlineKeyboardButton(text=label, callback_data=f"gr_rcpt:{data}"))
    builder.row(InlineKeyboardButton(text="✏️ Другое", callback_data="gr_rcpt:custom"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_style"))
    return builder.as_markup()


def greeting_occasion_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i in range(0, len(GREETING_OCCASIONS), 2):
        row = []
        for label, data in GREETING_OCCASIONS[i:i+2]:
            row.append(InlineKeyboardButton(text=label, callback_data=f"gr_occ:{data}"))
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="✏️ Другое", callback_data="gr_occ:custom"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_gr_name"))
    return builder.as_markup()


def greeting_mood_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, data in GREETING_MOODS:
        builder.row(InlineKeyboardButton(text=label, callback_data=f"gr_mood:{data}"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_gr_occasion"))
    return builder.as_markup()


# ─── Balance / Buy page ───

def balance_kb() -> InlineKeyboardMarkup:
    """Balance page with tariffs, Telegram Stars, and referral."""
    builder = InlineKeyboardBuilder()
    for pkg in config.credit_packages:
        builder.row(
            InlineKeyboardButton(
                text=pkg["label"],
                callback_data=f"buy_credits:{pkg['credits']}:{pkg['stars']}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="⭐ Оплата Telegram Stars", callback_data="buy_stars"),
    )
    builder.row(
        InlineKeyboardButton(text="🔗 Реферальная программа", callback_data="invite"),
    )
    return builder.as_markup()


def stars_kb() -> InlineKeyboardMarkup:
    """Telegram Stars payment options."""
    builder = InlineKeyboardBuilder()
    for pkg in config.credit_packages:
        builder.row(
            InlineKeyboardButton(
                text=f"{pkg['stars']}⭐ — {pkg['credits']} баллов",
                callback_data=f"buy_credits:{pkg['credits']}:{pkg['stars']}",
            )
        )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_balance"))
    return builder.as_markup()


# ─── Result keyboard ───

def track_kb(gen_id: int, idx: int) -> InlineKeyboardMarkup:
    """Per-track inline keyboard: share + rate."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📤 Поделиться песней", switch_inline_query=f"track_{gen_id}_{idx}"),
    )
    # Rating row
    star_labels = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    rating_row = []
    for i, label in enumerate(star_labels, 1):
        rating_row.append(
            InlineKeyboardButton(text=label, callback_data=f"rate:{gen_id}:{i}")
        )
    builder.row(*rating_row)
    return builder.as_markup()


def history_track_kb(gen_id: int, idx: int) -> InlineKeyboardMarkup:
    """Per-track keyboard for history: share only (no rating)."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📤 Поделиться песней", switch_inline_query=f"track_{gen_id}_{idx}"),
    )
    return builder.as_markup()


def after_generation_kb(gen_id: int) -> InlineKeyboardMarkup:
    """Keyboard shown after all tracks: regenerate + create another."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔄 Ещё варианты (−1🎵)", callback_data=f"regenerate:{gen_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="🎵 Создать другую", callback_data="create"),
    )
    return builder.as_markup()


def rating_kb(gen_id: int) -> InlineKeyboardMarkup:
    """Standalone rating keyboard with 5 stars."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Оцените песню:", callback_data="noop"),
    )
    star_labels = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    rating_row = []
    for i, label in enumerate(star_labels, 1):
        rating_row.append(
            InlineKeyboardButton(text=label, callback_data=f"rate:{gen_id}:{i}")
        )
    builder.row(*rating_row)
    return builder.as_markup()
