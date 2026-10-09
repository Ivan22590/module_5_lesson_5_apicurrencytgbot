"""Хендлеры расходов: баланс, история (пагинация), учёт трат."""

from __future__ import annotations

import html
import logging
import math
from typing import TYPE_CHECKING

from telebot import types

import database as db
import keyboards
from config import DB_PATH
from states import State, get_state, reset_state, set_state, user_data
from utils import (
    CATEGORIES,
    category_emoji,
    format_date,
    format_money,
    format_rate_display,
    parse_amount,
    safe_handler,
)

if TYPE_CHECKING:
    import telebot

logger = logging.getLogger(__name__)

PAGE_SIZE = 5
NOT_A_NUMBER_TEXT = "Пожалуйста, отправьте число"
NO_TRIP_TEXT = (
    "Нет активного путешествия. Создайте его кнопкой "
    "«🆕 Создать путешествие» или выберите «📂 Мои путешествия»."
)


# ---------------------------------------------------------------------------
# Баланс
# ---------------------------------------------------------------------------

def show_balance(bot: "telebot.TeleBot", chat_id: int, user_id: int) -> None:
    """Показывает баланс активного путешествия в обеих валютах.

    Args:
        bot: Экземпляр ``TeleBot``.
        chat_id: Идентификатор чата.
        user_id: Telegram-id пользователя.
    """
    balance = db.get_balance(DB_PATH, user_id)
    if balance is None:
        bot.send_message(chat_id, NO_TRIP_TEXT)
        return

    trip = balance["trip"]
    from_cur = str(trip["from_currency"])
    to_cur = str(trip["to_currency"])
    rate = float(trip["rate"])
    rate_note = "вручную" if trip["rate_manual"] else "API"

    text = (
        f"💰 Баланс <b>«{html.escape(str(trip['title']))}»</b>\n\n"
        f"Остаток: <b>{format_money(float(balance['balance_dest']), to_cur)}</b>"
        f" ≈ {format_money(float(balance['balance_home']), from_cur)}\n"
        f"Потрачено: {format_money(float(balance['spent_dest']), to_cur)}"
        f" ≈ {format_money(float(balance['spent_home']), from_cur)}"
        f" ({balance['expense_count']} записей)\n"
        f"Курс: {format_rate_display(rate, from_cur, to_cur)} ({rate_note})"
    )
    bot.send_message(chat_id, text, parse_mode="HTML")


# ---------------------------------------------------------------------------
# История расходов с пагинацией
# ---------------------------------------------------------------------------

def build_history_text(
    user_id: int, page: int, total_pages: int
) -> tuple[str, types.InlineKeyboardMarkup | None]:
    """Формирует текст страницы истории и клавиатуру пагинации.

    Args:
        user_id: Telegram-id пользователя.
        page: Номер страницы (с 1).
        total_pages: Всего страниц.

    Returns:
        Кортеж (текст, разметка клавиатуры или ``None``).
    """
    trip = db.get_active_trip(DB_PATH, user_id)
    if trip is None:
        return NO_TRIP_TEXT, keyboards.back_to_menu()

    from_cur = str(trip["from_currency"])
    to_cur = str(trip["to_currency"])
    totals = db.get_expense_totals(DB_PATH, user_id, int(trip["id"]))
    count = int(totals["count"])

    header = (
        f"📊 История расходов — "
        f"<b>«{html.escape(str(trip['title']))}»</b>\n"
        f"Страница {page}/{total_pages}\n"
    )

    if count == 0:
        return (
            header + "\nРасходов пока не было. Отправьте число, чтобы записать трату.",
            keyboards.back_to_menu(),
        )

    offset = (page - 1) * PAGE_SIZE
    rows = db.get_expenses_page(DB_PATH, user_id, int(trip["id"]), PAGE_SIZE, offset)

    lines = [header]
    for index, row in enumerate(rows, start=offset + 1):
        emoji = category_emoji(str(row["category"]))
        lines.append(
            f"\n{index}. {emoji} {format_money(float(row['amount']), to_cur)} "
            f"(≈ {format_money(float(row['amount_home']), from_cur)})"
        )
        lines.append(f"   📅 {format_date(str(row['created_at']))}")

    balance = db.get_balance(DB_PATH, user_id)
    lines.append(
        f"\nИтого: {format_money(float(totals['amount']), to_cur)}"
        f" ≈ {format_money(float(totals['amount_home']), from_cur)}"
    )
    if balance is not None:
        lines.append(
            f"Остаток: {format_money(float(balance['balance_dest']), to_cur)}"
            f" ≈ {format_money(float(balance['balance_home']), from_cur)}"
        )

    return "\n".join(lines), keyboards.history_pagination(page, total_pages)


def show_history(
    bot: "telebot.TeleBot", chat_id: int, user_id: int, page: int,
    message_id: int | None = None,
) -> None:
    """Показывает страницу истории расходов.

    Args:
        bot: Экземпляр ``TeleBot``.
        chat_id: Идентификатор чата.
        user_id: Telegram-id пользователя.
        page: Номер страницы (с 1).
        message_id: Идентификатор сообщения для редактирования.
    """
    trip = db.get_active_trip(DB_PATH, user_id)
    if trip is None:
        bot.send_message(chat_id, NO_TRIP_TEXT)
        return

    count = int(db.get_expense_totals(DB_PATH, user_id, int(trip["id"]))["count"])
    total_pages = max(1, math.ceil(count / PAGE_SIZE))
    page = max(1, min(page, total_pages))

    text, markup = build_history_text(user_id, page, total_pages)

    if message_id is not None:
        try:
            bot.edit_message_text(
                text, chat_id, message_id, parse_mode="HTML", reply_markup=markup
            )
        except Exception:  # noqa: BLE001 - Telegram ругается на неизменный текст
            logger.debug("Не удалось отредактировать сообщение истории")
    else:
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)


# ---------------------------------------------------------------------------
# Учёт расхода
# ---------------------------------------------------------------------------

def begin_expense(
    bot: "telebot.TeleBot", chat_id: int, user_id: int, amount: float
) -> None:
    """Начинает оформление расхода: конвертирует и просит выбрать категорию.

    Args:
        bot: Экземпляр ``TeleBot``.
        chat_id: Идентификатор чата.
        user_id: Telegram-id пользователя.
        amount: Сумма в валюте страны назначения.
    """
    trip = db.get_active_trip(DB_PATH, user_id)
    if trip is None:
        bot.send_message(chat_id, NO_TRIP_TEXT)
        return

    rate = float(trip["rate"])
    if rate <= 0:
        bot.send_message(chat_id, "Не удалось определить курс путешествия.")
        return

    amount_home = amount / rate
    data = user_data(user_id)
    data.clear()
    data.update(amount=amount, amount_home=amount_home, rate=rate)
    set_state(user_id, State.EXPENSE_CATEGORY)

    bot.send_message(
        chat_id,
        f"💸 Потрачено: <b>{format_money(amount, str(trip['to_currency']))}</b>"
        f" ≈ {format_money(amount_home, str(trip['from_currency']))}\n\n"
        "Выберите категорию расхода:",
        parse_mode="HTML",
        reply_markup=keyboards.categories(),
    )


def handle_category(
    bot: "telebot.TeleBot", chat_id: int, user_id: int, category_key: str
) -> None:
    """Сохраняет выбранную категорию и показывает подтверждение.

    Args:
        bot: Экземпляр ``TeleBot``.
        chat_id: Идентификатор чата.
        user_id: Telegram-id пользователя.
        category_key: Ключ категории (``food``, ``hotel``, ...).
    """
    if get_state(user_id) != State.EXPENSE_CATEGORY:
        bot.send_message(chat_id, "Сначала введите сумму расхода числом.")
        return

    category = CATEGORIES.get(category_key)
    if category is None:
        bot.send_message(chat_id, "Неизвестная категория. Попробуйте ещё раз.")
        return

    emoji, label = category
    data = user_data(user_id)
    data["category"] = label

    trip = db.get_active_trip(DB_PATH, user_id)
    if trip is None:
        reset_state(user_id)
        bot.send_message(chat_id, NO_TRIP_TEXT)
        return

    set_state(user_id, State.EXPENSE_CONFIRM)
    bot.send_message(
        chat_id,
        f"{format_money(float(data['amount']), str(trip['to_currency']))} = "
        f"{format_money(float(data['amount_home']), str(trip['from_currency']))}\n"
        f"{emoji} Категория: <b>{label}</b>\n\n"
        "Записать расход?",
        parse_mode="HTML",
        reply_markup=keyboards.expense_confirmation(),
    )


def commit_expense(bot: "telebot.TeleBot", chat_id: int, user_id: int) -> None:
    """Записывает расход в БД и показывает обновлённый остаток.

    Args:
        bot: Экземпляр ``TeleBot``.
        chat_id: Идентификатор чата.
        user_id: Telegram-id пользователя.
    """
    if get_state(user_id) != State.EXPENSE_CONFIRM:
        bot.send_message(chat_id, "Нет расхода для подтверждения.")
        return

    data = user_data(user_id)
    trip = db.get_active_trip(DB_PATH, user_id)
    if trip is None:
        reset_state(user_id)
        bot.send_message(chat_id, NO_TRIP_TEXT)
        return

    amount = float(data["amount"])
    amount_home = float(data["amount_home"])
    rate = float(data["rate"])
    category = str(data.get("category", "Прочее"))

    db.add_expense(DB_PATH, int(trip["id"]), amount, amount_home, rate, category)
    reset_state(user_id)

    balance = db.get_balance(DB_PATH, user_id)
    from_cur = str(trip["from_currency"])
    to_cur = str(trip["to_currency"])
    emoji = category_emoji(category)

    lines = [
        f"✅ Учтено: {emoji} {format_money(amount, to_cur)} "
        f"(≈ {format_money(amount_home, from_cur)})",
    ]
    if balance is not None:
        lines.append("")
        lines.append(
            f"Остаток: <b>{format_money(float(balance['balance_dest']), to_cur)}</b>"
            f" ≈ {format_money(float(balance['balance_home']), from_cur)}"
        )
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")


def cancel_expense(bot: "telebot.TeleBot", chat_id: int, user_id: int) -> None:
    """Отменяет оформление расхода.

    Args:
        bot: Экземпляр ``TeleBot``.
        chat_id: Идентификатор чата.
        user_id: Telegram-id пользователя.
    """
    reset_state(user_id)
    bot.send_message(chat_id, "Расход отменён. Отправьте число, чтобы записать новый.")


# ---------------------------------------------------------------------------
# Регистрация хендлеров
# ---------------------------------------------------------------------------

def register(bot: "telebot.TeleBot") -> None:
    """Регистрирует хендлеры расходов.

    Хендлер числового ввода и фолбэк регистрируются последними,
    чтобы FSM-состояния из :mod:`handlers.trip` обрабатывались раньше.

    Args:
        bot: Экземпляр ``TeleBot``.
    """

    @bot.message_handler(
        func=lambda m: (
            parse_amount(m.text or "") is not None
            and get_state(m.from_user.id)
            in (State.IDLE, State.EXPENSE_CATEGORY, State.EXPENSE_CONFIRM)
        ),
        pass_bot=True,
    )
    @safe_handler
    def on_amount(message: types.Message, bot: "telebot.TeleBot | None" = None) -> None:
        """Любое сообщение-число = трата в валюте страны назначения."""
        assert bot is not None
        amount = parse_amount(message.text or "")
        if amount is None:
            bot.send_message(message.chat.id, NOT_A_NUMBER_TEXT)
            return
        begin_expense(bot, message.chat.id, message.from_user.id, amount)

    @bot.message_handler(
        func=lambda m: get_state(m.from_user.id) == State.EXPENSE_CATEGORY,
        pass_bot=True,
    )
    @safe_handler
    def fsm_category_text(message: types.Message, bot: "telebot.TeleBot | None" = None) -> None:
        """Просит выбрать категорию кнопкой, если пришёл нечисловой текст."""
        assert bot is not None
        bot.send_message(message.chat.id, "Пожалуйста, выберите категорию кнопкой ниже.")

    @bot.message_handler(func=lambda m: True, pass_bot=True)
    @safe_handler
    def fallback(message: types.Message, bot: "telebot.TeleBot | None" = None) -> None:
        """Фолбэк: подсказка для любого нераспознанного текста."""
        assert bot is not None
        text = (message.text or "").strip()
        if text.startswith("/"):
            bot.send_message(
                message.chat.id,
                "Неизвестная команда. Введите /start, чтобы открыть меню.",
            )
            return
        state = get_state(message.from_user.id)
        if state == State.EXPENSE_CONFIRM:
            bot.send_message(
                message.chat.id,
                "Подтвердите или отмените расход кнопками ниже.",
            )
            return
        if state in (State.TRIP_AMOUNT, State.TRIP_MANUAL_RATE, State.RATE_EDIT):
            bot.send_message(message.chat.id, NOT_A_NUMBER_TEXT)
            return
        bot.send_message(
            message.chat.id,
            "Отправьте число — я запишу расход 💸\n"
            "Или выберите пункт меню ниже 👇",
            reply_markup=keyboards.main_menu(),
        )
