"""Inline keyboard builders for the bot."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import config


def main_menu_kb(credits: int, free_left: int) -> InlineKeyboardMarkup:
    total = credits + free_left
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎵 Создать трек", callback_data="create"),
        InlineKeyboardButton(text="📚 Мои треки", callback_data="history"),
    )
    builder.row(
        InlineKeyboardButton(text=f"🎵 Песни: {total}", callback_data="buy"),
        InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
    )
    builder.row(
        InlineKeyboardButton(text="📤 Поделиться", callback_data="invite"),
        InlineKeyboardButton(text="❓ Помощь", callback_data="help"),
    )
    return builder.as_markup()


def gender_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🚹 Мужской", callback_data="gender:male"),
        InlineKeyboardButton(text="🚺 Женский", callback_data="gender:female"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu"))
    return builder.as_markup()


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
    ("✏️ Свой стиль", "custom_style"),
]


def style_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    # All styles except last (custom) in rows of 3
    regular_styles = [s for s in STYLES if s[1] != "custom_style"]
    for i in range(0, len(regular_styles), 3):
        row = []
        for label, data in regular_styles[i:i+3]:
            row.append(InlineKeyboardButton(text=label, callback_data=f"style:{data}"))
        builder.row(*row)
    # Custom style button
    builder.row(InlineKeyboardButton(text="✏️ Свой стиль", callback_data="style:custom_style"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_gender"))
    return builder.as_markup()


def result_kb(gen_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔊 Вариант 1", callback_data=f"listen:{gen_id}:0"),
        InlineKeyboardButton(text="🔊 Вариант 2", callback_data=f"listen:{gen_id}:1"),
    )
    builder.row(
        InlineKeyboardButton(text="📥 Скачать #1 (−1🎵)", callback_data=f"download:{gen_id}:0"),
        InlineKeyboardButton(text="📥 Скачать #2 (−1🎵)", callback_data=f"download:{gen_id}:1"),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Ещё варианты (−1🎵)", callback_data=f"regenerate:{gen_id}"),
    )
    # Rating: "Оцените песню:" label + 5 stars (left empty, right filled)
    builder.row(
        InlineKeyboardButton(text="Оцените песню:", callback_data="noop"),
    )
    # Stars: ☆ | ☆⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐
    star_labels = ["☆", "☆⭐", "⭐⭐⭐", "⭐⭐⭐⭐", "⭐⭐⭐⭐⭐"]
    rating_row = []
    for i, label in enumerate(star_labels, 1):
        rating_row.append(
            InlineKeyboardButton(text=label, callback_data=f"rate:{gen_id}:{i}")
        )
    builder.row(*rating_row)
    builder.row(
        InlineKeyboardButton(text="🏠 Меню", callback_data="back_menu"),
    )
    return builder.as_markup()


def rating_kb(gen_id: int) -> InlineKeyboardMarkup:
    """Standalone rating keyboard with 5 stars."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Оцените песню:", callback_data="noop"),
    )
    star_labels = ["☆", "☆⭐", "⭐⭐⭐", "⭐⭐⭐⭐", "⭐⭐⭐⭐⭐"]
    rating_row = []
    for i, label in enumerate(star_labels, 1):
        rating_row.append(
            InlineKeyboardButton(text=label, callback_data=f"rate:{gen_id}:{i}")
        )
    builder.row(*rating_row)
    return builder.as_markup()


def buy_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for pkg in config.credit_packages:
        builder.row(
            InlineKeyboardButton(
                text=pkg["label"],
                callback_data=f"buy_credits:{pkg['credits']}:{pkg['stars']}",
            )
        )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu"))
    return builder.as_markup()


def back_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Меню", callback_data="back_menu")]
    ])
