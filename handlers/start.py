"""Хендлеры /start и главного меню (Reply-кнопки и команды-дубликаты)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telebot import types

import database as db
import keyboards
from config import DB_PATH
from states import reset_state
from utils import safe_handler

if TYPE_CHECKING:
    import telebot

logger = logging.getLogger(__name__)

# Команды-дубликаты пунктов меню
COMMAND_ACTIONS: dict[str, str] = {
    "newtrip": "newtrip",
    "switch": "trips",
    "balance": "balance",
    "history": "history",
    "setrate": "setrate",
}

WELCOME_TEXT = (
    "👋 Привет! Я — <b>Мини-кошелёк путешественника</b>.\n\n"
    "Я помогу отслеживать расходы в поездке сразу в двух валютах: "
    "домашней и валюте страны назначения.\n\n"
    "Выберите пункт меню ниже 👇"
)


def dispatch_menu(bot: "telebot.TeleBot", message: types.Message, action: str) -> None:
    """Диспетчеризует нажатие пункта главного меню.

    Args:
        bot: Экземпляр ``TeleBot``.
        message: Сообщение пользователя.
        action: Ключ действия (``newtrip``, ``trips``, ...).
    """
    # Импорты внутри функции — чтобы избежать циклических зависимостей
    from handlers import expense, trip

    user_id = message.from_user.id
    chat_id = message.chat.id

    if action == "newtrip":
        trip.begin_trip_creation(bot, message)
    elif action == "trips":
        reset_state(user_id)
        trip.show_trip_list(bot, chat_id, user_id)
    elif action == "balance":
        reset_state(user_id)
        expense.show_balance(bot, chat_id, user_id)
    elif action == "history":
        reset_state(user_id)
        expense.show_history(bot, chat_id, user_id, page=1)
    elif action == "setrate":
        trip.begin_rate_edit(bot, message)
    else:  # pragma: no cover - защита от неизвестного действия
        logger.warning("Неизвестное действие меню: %s", action)


def register(bot: "telebot.TeleBot") -> None:
    """Регистрирует хендлеры /start и главного меню.

    Args:
        bot: Экземпляр ``TeleBot``.
    """

    @bot.message_handler(commands=["start"], pass_bot=True)
    @safe_handler
    def cmd_start(message: types.Message, bot: "telebot.TeleBot | None" = None) -> None:
        """Регистрирует пользователя и показывает главное меню."""
        assert bot is not None
        db.register_user(DB_PATH, message.from_user.id)
        reset_state(message.from_user.id)
        bot.send_message(
            message.chat.id,
            WELCOME_TEXT,
            parse_mode="HTML",
            reply_markup=keyboards.main_menu(),
        )

    @bot.message_handler(
        func=lambda m: m.text in keyboards.MENU_ITEMS, pass_bot=True
    )
    @safe_handler
    def menu_click(message: types.Message, bot: "telebot.TeleBot | None" = None) -> None:
        """Обрабатывает нажатие кнопки Reply-меню."""
        assert bot is not None
        action = keyboards.MENU_ITEMS.get(message.text or "")
        if action:
            dispatch_menu(bot, message, action)

    @bot.message_handler(commands=list(COMMAND_ACTIONS), pass_bot=True)
    @safe_handler
    def command_alias(message: types.Message, bot: "telebot.TeleBot | None" = None) -> None:
        """Обрабатывает команды-дубликаты: /newtrip, /switch, /balance, ..."""
        assert bot is not None
        command = (message.text or "").split()[0].lstrip("/").split("@")[0]
        action = COMMAND_ACTIONS.get(command)
        if action:
            dispatch_menu(bot, message, action)
