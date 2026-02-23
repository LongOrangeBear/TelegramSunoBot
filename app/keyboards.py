"""Keyboard builders for the bot — Reply keyboard + Inline keyboards."""

from urllib.parse import quote

from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import config


def _share_url(user_id: int) -> str:
    """Build a t.me/share/url link with referral deep link."""
    bot_link = f"https://t.me/{config.bot_username}?start=ref{user_id}"
    text = (
        "🎵 Послушай какую песню мне создал ИИ!\n"
        "Попробуй сам → " + bot_link + "\n\n"
        "🎁 +1 песня за каждого друга, который запустит бота!"
    )
    return f"https://t.me/share/url?url={quote(bot_link)}&text={quote(text)}"


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
    builder.row(
        InlineKeyboardButton(text="📱 Песня для сторис", callback_data="mode:stories"),
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


# ─── Stories wizard keyboards ───

STORIES_VIBES = [
    ("👑 Босс", "boss"),
    ("🌿 На чиле", "chill"),
    ("🔥 В огне", "fire"),
    ("💔 Грустно", "sad"),
    ("🎉 Праздник", "party"),
    ("🏋️ Спорт", "sport"),
    ("☕ Уютно", "cozy"),
    ("😎 Дерзкий", "swagger"),
    ("✨ Мечтатель", "dreamer"),
]

STORIES_VIBE_LABELS = {
    "boss": "босс, я главный",
    "chill": "на чиле, расслабленно",
    "fire": "в огне, энергия",
    "sad": "грустно, меланхолия",
    "party": "праздник, веселье",
    "sport": "спорт и мотивация",
    "cozy": "уютно, тепло",
    "swagger": "дерзкий вайб, крутой",
    "dreamer": "мечтатель, в облаках",
}

STORIES_MOODS = [
    ("😎 Дерзко", "bold"),
    ("🥰 Мило", "cute"),
    ("😂 Прикольно", "funny"),
    ("🌙 Лирично", "dreamy"),
    ("💪 Энергично", "powerful"),
    ("🌸 Нежно", "gentle"),
    ("🌆 Вечернее", "evening"),
    ("😈 Провокационно", "provocative"),
    ("🌞 Позитивно", "sunny"),
]

STORIES_MOOD_LABELS = {
    "bold": "дерзко и уверенно",
    "cute": "мило и романтично",
    "funny": "прикольно, с юмором",
    "dreamy": "мечтательно и лирично",
    "powerful": "мощно и энергично",
    "gentle": "нежно и спокойно",
    "evening": "вечернее, атмосферное",
    "provocative": "провокационно и дерзко",
    "sunny": "солнечно и позитивно",
}


def stories_vibe_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i in range(0, len(STORIES_VIBES), 3):
        row = []
        for label, data in STORIES_VIBES[i:i+3]:
            row.append(InlineKeyboardButton(text=label, callback_data=f"st_vibe:{data}"))
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="✏️ Свой вайб", callback_data="st_vibe:custom"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_style"))
    return builder.as_markup()


def stories_mood_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i in range(0, len(STORIES_MOODS), 3):
        row = []
        for label, data in STORIES_MOODS[i:i+3]:
            row.append(InlineKeyboardButton(text=label, callback_data=f"st_mood:{data}"))
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_st_vibe"))
    return builder.as_markup()


def stories_name_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⏩ Пропустить имя", callback_data="st_name:skip"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_st_context"))
    return builder.as_markup()


# ─── Balance / Buy page ───

def balance_kb() -> InlineKeyboardMarkup:
    """Balance page — choose payment method."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⭐ Оплата Telegram Stars", callback_data="buy_stars"),
    )
    if config.tbank_enabled:
        builder.row(
            InlineKeyboardButton(text="💳 Оплата картой", callback_data="buy_card"),
        )
    builder.row(
        InlineKeyboardButton(text="🔗 Реферальная программа", callback_data="invite"),
    )
    return builder.as_markup()


def card_kb() -> InlineKeyboardMarkup:
    """T-Bank card payment options (ruble prices)."""
    builder = InlineKeyboardBuilder()
    for pkg in config.credit_packages_rub:
        builder.row(
            InlineKeyboardButton(
                text=pkg["label"],
                callback_data=f"buy_tbank:{pkg['credits']}:{pkg['rub']}",
            )
        )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_balance"))
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

def preview_track_kb(gen_id: int, idx: int, user_id: int = 0) -> InlineKeyboardMarkup:
    """Per-track keyboard for preview (free generation): buy + share."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🎵 Купить полный трек — 1🎵",
            callback_data=f"buy_track:{gen_id}:{idx}",
        ),
    )
    if user_id:
        builder.row(
            InlineKeyboardButton(
                text="📤 Поделиться (+1🎵 за друга)",
                url=_share_url(user_id),
            ),
        )
    return builder.as_markup()


def track_kb(gen_id: int, idx: int, user_id: int = 0) -> InlineKeyboardMarkup:
    """Per-track inline keyboard: download + share (for paid/unlocked tracks)."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="⬇️ Скачать файл",
            callback_data=f"download:{gen_id}:{idx}",
        ),
    )
    if user_id:
        builder.row(
            InlineKeyboardButton(
                text="📤 Поделиться (+1🎵 за друга)",
                url=_share_url(user_id),
            ),
        )
    return builder.as_markup()


def history_track_kb(gen_id: int, idx: int, user_id: int = 0) -> InlineKeyboardMarkup:
    """Per-track keyboard for history: download + share."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="⬇️ Скачать файл",
            callback_data=f"download:{gen_id}:{idx}",
        ),
    )
    if user_id:
        builder.row(
            InlineKeyboardButton(
                text="📤 Поделиться (+1🎵 за друга)",
                url=_share_url(user_id),
            ),
        )
    return builder.as_markup()


def preview_after_generation_kb(gen_id: int) -> InlineKeyboardMarkup:
    """Keyboard shown after preview tracks: rate + feedback + create another."""
    builder = InlineKeyboardBuilder()
    # Rating label
    builder.row(
        InlineKeyboardButton(text="⭐ Оцените результат:", callback_data="noop"),
    )
    star_labels = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    rating_row = [
        InlineKeyboardButton(text=label, callback_data=f"rate:{gen_id}:{i}")
        for i, label in enumerate(star_labels, 1)
    ]
    builder.row(*rating_row)
    builder.row(
        InlineKeyboardButton(
            text="✍️ Оставить комментарий / предложение",
            callback_data=f"feedback:{gen_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="🎵 Создать новую песню", callback_data="create"),
    )
    return builder.as_markup()


def after_generation_kb(gen_id: int) -> InlineKeyboardMarkup:
    """Keyboard shown after all tracks: rate + feedback + regenerate + create another."""
    builder = InlineKeyboardBuilder()
    # Rating label
    builder.row(
        InlineKeyboardButton(text="⭐ Оцените результат:", callback_data="noop"),
    )
    star_labels = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    rating_row = [
        InlineKeyboardButton(text=label, callback_data=f"rate:{gen_id}:{i}")
        for i, label in enumerate(star_labels, 1)
    ]
    builder.row(*rating_row)
    builder.row(
        InlineKeyboardButton(
            text="✍️ Оставить комментарий / предложение",
            callback_data=f"feedback:{gen_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Ещё варианты (−1🎵)", callback_data=f"regenerate:{gen_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="🎵 Создать новую песню", callback_data="create"),
    )
    return builder.as_markup()
