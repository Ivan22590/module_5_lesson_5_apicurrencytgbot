"""Обработка всех inline-кнопок (callback-запросов)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telebot import types

import keyboards
from handlers import expense, trip
from states import reset_state
from utils import safe_handler

if TYPE_CHECKING:
    import telebot

logger = logging.getLogger(__name__)


def _answer(bot: "telebot.TeleBot", call: types.CallbackQuery, text: str = "") -> None:
    """Отвечает на callback-запрос, подавляя «часики» на кнопке.

    Args:
        bot: Экземпляр ``TeleBot``.
        call: Callback-запрос.
        text: Текст всплывающего уведомления.
    """
    try:
        bot.answer_callback_query(call.id, text)
    except Exception:  # noqa: BLE001 - ответ может не дойти, это не критично
        logger.debug("Не удалось ответить на callback %s", call.id)


def register(bot: "telebot.TeleBot") -> None:
    """Регистрирует единый обработчик callback-запросов.

    Args:
        bot: Экземпляр ``TeleBot``.
    """

    @bot.callback_query_handler(func=lambda c: True, pass_bot=True)
    @safe_handler
    def on_callback(call: types.CallbackQuery, bot: "telebot.TeleBot | None" = None) -> None:
        """Маршрутизирует callback-запросы по префиксам.

        Гарантирует, что на callback всегда будет отправлен ответ:
        иначе Telegram долго показывает «часики» на кнопке.
        """
        assert bot is not None
        answered = False

        def answer(text: str = "") -> None:
            """Отвечает на callback и помечает ответ отправленным."""
            nonlocal answered
            _answer(bot, call, text)
            answered = True

        try:
            _dispatch(call, bot, answer)
        finally:
            if not answered:
                _answer(bot, call)


def _dispatch(call: types.CallbackQuery, bot: "telebot.TeleBot", answer) -> None:
    """Маршрутизирует callback-запрос по префиксам ``call.data``.

    Args:
        call: Callback-запрос.
        bot: Экземпляр ``TeleBot``.
        answer: Функция ``(text="")`` — ответ на callback.
    """
    data = call.data or ""
    user_id = call.from_user.id
    chat_id = call.message.chat.id if call.message else None
    message_id = call.message.message_id if call.message else None
    if chat_id is None:
        answer()
        return

    # --- Выбор страны при создании путешествия: pick:<этап>:<код> ---
    if data.startswith("pick:"):
        answer()
        parts = data.split(":")
        if len(parts) != 3:
            return
        _, stage, code = parts
        if stage == "from":
            trip.handle_from_country(bot, chat_id, user_id, code, from_button=True)
        else:
            trip.handle_to_country(bot, chat_id, user_id, code, from_button=True)
        return

    # --- Подтверждение курса при создании ---
    if data == "rate:yes":
        answer()
        trip.confirm_rate_yes(bot, chat_id, user_id)
        return
    if data == "rate:no":
        answer("Вводим курс вручную")
        trip.confirm_rate_no(bot, chat_id, user_id)
        return

    # --- Переключение путешествия: trip:<id> ---
    if data.startswith("trip:"):
        try:
            trip_id = int(data.split(":", 1)[1])
        except (IndexError, ValueError):
            answer("Некорректный идентификатор")
            return
        trip.switch_trip(bot, call, trip_id)
        return

    # --- Категория расхода: cat:<key> ---
    if data.startswith("cat:"):
        answer()
        key = data.split(":", 1)[1]
        expense.handle_category(bot, chat_id, user_id, key)
        return

    # --- Подтверждение расхода ---
    if data == "expense:yes":
        answer("Расход записан ✅")
        expense.commit_expense(bot, chat_id, user_id)
        return
    if data == "expense:no":
        answer()
        expense.cancel_expense(bot, chat_id, user_id)
        return

    # --- Пагинация истории: hist:<page> | hist:noop ---
    if data.startswith("hist:"):
        page_raw = data.split(":", 1)[1]
        if page_raw == "noop":
            answer()
            return
        try:
            page = int(page_raw)
        except ValueError:
            answer()
            return
        answer()
        if message_id is not None:
            expense.show_history(bot, chat_id, user_id, page, message_id=message_id)
        return

    # --- Кнопка «В меню» ---
    if data == "menu":
        answer()
        reset_state(user_id)
        if message_id is not None:
            try:
                bot.edit_message_reply_markup(
                    chat_id, message_id, reply_markup=None
                )
            except Exception:  # noqa: BLE001 - сообщение могло не измениться
                logger.debug("Не удалось убрать inline-клавиатуру")
        bot.send_message(
            chat_id,
            "Главное меню 👇",
            reply_markup=keyboards.main_menu(),
        )
        return

    logger.warning("Необработанный callback: %s", data)
    answer()
