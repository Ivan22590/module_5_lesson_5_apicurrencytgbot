"""Пакет хендлеров Telegram-бота.

Модуль отвечает за регистрацию всех хендлеров в правильном порядке:
сначала команды и главное меню, затем FSM-ходы, затем inline-кнопки.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import telebot


def register_handlers(bot: "telebot.TeleBot") -> None:
    """Регистрирует все хендлеры бота.

    Порядок важен: хендлеры telebot проверяются в порядке регистрации.

    Args:
        bot: Экземпляр ``TeleBot``.
    """
    from handlers import start, trip, expense, callbacks

    start.register(bot)      # /start, главное меню, команды-дубликаты
    trip.register(bot)       # FSM создания путешествия, переключение, /setrate
    expense.register(bot)    # учёт расходов, баланс, история
    callbacks.register(bot)  # все inline-кнопки
