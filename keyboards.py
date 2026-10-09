"""Все Reply- и Inline-клавиатуры бота."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from telebot import types

from utils import CATEGORIES

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Тексты пунктов главного меню (для распознавания нажатий)
# ---------------------------------------------------------------------------

MENU_ITEMS: dict[str, str] = {
    "🆕 Создать путешествие": "newtrip",
    "📂 Мои путешествия": "trips",
    "💰 Баланс": "balance",
    "📊 История расходов": "history",
    "⚙️ Изменить курс": "setrate",
}

# Популярные страны: отображаемое название → ISO-код
POPULAR_COUNTRIES: list[tuple[str, str]] = [
    ("🇷🇺 Россия", "RU"),
    ("🇹🇷 Турция", "TR"),
    ("🇹🇭 Таиланд", "TH"),
    ("🇨🇳 Китай", "CN"),
    ("🇦🇪 ОАЭ", "AE"),
    ("🇪🇬 Египет", "EG"),
    ("🇬🇪 Грузия", "GE"),
    ("🇦🇲 Армения", "AM"),
    ("🇰🇿 Казахстан", "KZ"),
    ("🇺🇿 Узбекистан", "UZ"),
    ("🇻🇳 Вьетнам", "VN"),
    ("🇮🇩 Индонезия", "ID"),
    ("🇲🇾 Малайзия", "MY"),
    ("🇮🇹 Италия", "IT"),
    ("🇪🇸 Испания", "ES"),
    ("🇯🇵 Япония", "JP"),
]


def main_menu() -> types.ReplyKeyboardMarkup:
    """Создаёт главное Reply-меню (5 кнопок, каждая на своей строке).

    Returns:
        Разметка Reply-клавиатуры.
    """
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    for text in MENU_ITEMS:
        keyboard.add(types.KeyboardButton(text))
    return keyboard


def popular_countries(prefix: str = "from") -> types.InlineKeyboardMarkup:
    """Inline-кнопки со списком популярных стран.

    Args:
        prefix: Этап FSM (``"from"`` или ``"to"``) — попадает в callback_data.

    Returns:
        Разметка inline-клавиатуры.
    """
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        *[
            types.InlineKeyboardButton(
                text, callback_data=f"pick:{prefix}:{code}"
            )
            for text, code in POPULAR_COUNTRIES
        ]
    )
    return keyboard


def country_display(code: str) -> str:
    """Возвращает отображаемое название страны по ISO-коду.

    Args:
        code: ISO-код страны (2 буквы).

    Returns:
        Строка с флагом и названием либо сам код, если страна не найдена.
    """
    for text, country_code in POPULAR_COUNTRIES:
        if country_code == code.upper():
            return text
    return code


def rate_confirmation() -> types.InlineKeyboardMarkup:
    """Кнопки подтверждения курса: «Да» / «Нет».

    Returns:
        Разметка inline-клавиатуры.
    """
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("✅ Да", callback_data="rate:yes"),
        types.InlineKeyboardButton("❌ Нет", callback_data="rate:no"),
    )
    return keyboard


def trips_list(trips: list[sqlite3.Row]) -> types.InlineKeyboardMarkup:
    """Список путешествий пользователя для переключения.

    Args:
        trips: Строки путешествий из БД.

    Returns:
        Разметка inline-клавиатуры.
    """
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    for trip in trips:
        marker = "✅ " if trip["is_active"] else ""
        title = f"{marker}{trip['title']} ({trip['from_currency']}→{trip['to_currency']})"
        keyboard.add(
            types.InlineKeyboardButton(title, callback_data=f"trip:{trip['id']}")
        )
    keyboard.add(types.InlineKeyboardButton("🔙 В меню", callback_data="menu"))
    return keyboard


def categories() -> types.InlineKeyboardMarkup:
    """Inline-кнопки выбора категории расхода.

    Returns:
        Разметка inline-клавиатуры.
    """
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        *[
            types.InlineKeyboardButton(f"{emoji} {label}", callback_data=f"cat:{key}")
            for key, (emoji, label) in CATEGORIES.items()
        ]
    )
    return keyboard


def expense_confirmation() -> types.InlineKeyboardMarkup:
    """Кнопки подтверждения расхода: «Учесть» / «Отмена».

    Returns:
        Разметка inline-клавиатуры.
    """
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("✅ Учесть расход", callback_data="expense:yes"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="expense:no"),
    )
    return keyboard


def history_pagination(page: int, total_pages: int) -> types.InlineKeyboardMarkup:
    """Кнопки пагинации истории расходов.

    Args:
        page: Текущая страница (с 1).
        total_pages: Всего страниц.

    Returns:
        Разметка inline-клавиатуры.
    """
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    row: list[types.InlineKeyboardButton] = []
    if page > 1:
        row.append(
            types.InlineKeyboardButton("◀️ Назад", callback_data=f"hist:{page - 1}")
        )
    row.append(
        types.InlineKeyboardButton(f"{page}/{total_pages}", callback_data="hist:noop")
    )
    if page < total_pages:
        row.append(
            types.InlineKeyboardButton("Вперёд ▶️", callback_data=f"hist:{page + 1}")
        )
    keyboard.add(*row)
    keyboard.add(types.InlineKeyboardButton("🔙 В меню", callback_data="menu"))
    return keyboard


def back_to_menu() -> types.InlineKeyboardMarkup:
    """Кнопка возврата в главное меню.

    Returns:
        Разметка inline-клавиатуры.
    """
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🔙 В меню", callback_data="menu"))
    return keyboard
