"""Точка входа Telegram-бота «Мини-кошелёк путешественника».

Загружает конфигурацию, настраивает логирование, инициализирует базу
данных, подключает сквозное логирование входящих сообщений и исходящих
ответов бота, регистрирует хендлеры и запускает long-polling.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import telebot

import database as db
from config import ConfigError, load_settings, setup_logging
from handlers import register_handlers
from states import get_state

logger = logging.getLogger(__name__)

# Максимальная длина фрагмента текста, попадающего в одну строку лога
PREVIEW_LIMIT = 300

# Типы апдейтов, которые бот обязан получать.
#
# Указаны явно и неизменно: Telegram запоминает последнюю заданную настройку
# allowed_updates. При передаче None сервер продолжает применять старую, и
# если в ней нет "callback_query", все inline-кнопки молча перестают
# доходить до бота (сообщения приходят, нажатия — нет).
ALLOWED_UPDATES: list[str] = [
    "message",
    "edited_message",
    "callback_query",
    "inline_query",
]


def _preview(value: Any, limit: int = PREVIEW_LIMIT) -> str:
    """Сжимает значение до однострочной строки для записи в лог.

    Переводы строк заменяются пробелами, слишком длинный текст
    обрезается многоточием — лог остаётся читаемым.

    Args:
        value: Любое значение (текст сообщения, объект и т.п.).
        limit: Максимальная длина результата.

    Returns:
        Однострочное представление значения.
    """
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _describe_incoming(update: Any) -> str:
    """Формирует читаемое описание входящего апдейта.

    Args:
        update: Объект ``telebot.types.Update``.

    Returns:
        Строка вида ``message | user=... | state=... | text=...``.
    """
    if getattr(update, "message", None) is not None:
        msg = update.message
        user = msg.from_user
        user_id = getattr(user, "id", None)
        username = getattr(user, "username", None)
        return (
            f"message | user={user_id} (@{username or '—'}) "
            f"chat={msg.chat.id} | state={_state_name(user_id)} "
            f"| text={_preview(msg.text)!r}"
        )

    if getattr(update, "callback_query", None) is not None:
        call = update.callback_query
        user = call.from_user
        user_id = getattr(user, "id", None)
        username = getattr(user, "username", None)
        chat = getattr(call.message, "chat", None)
        return (
            f"callback | user={user_id} (@{username or '—'}) "
            f"chat={getattr(chat, 'id', '?')} | state={_state_name(user_id)} "
            f"| data={_preview(call.data, 120)!r}"
        )

    return f"прочий апдейт | update_id={getattr(update, 'update_id', '?')}"


def _state_name(user_id: Any) -> str:
    """Возвращает имя текущего FSM-состояния пользователя.

    Args:
        user_id: Telegram-id пользователя (может быть ``None``).

    Returns:
        Имя состояния (``idle``, ``trip_from``, ...) или ``?``.
    """
    if user_id is None:
        return "?"
    try:
        state = get_state(user_id)
    except Exception:  # noqa: BLE001 - логирование не должно ломать приём апдейта
        return "?"
    value = getattr(state, "value", state)
    return str(value)


def _describe_outgoing(name: str, args: tuple, kwargs: dict) -> str:
    """Формирует описание исходящего вызова Telegram API для лога.

    Args:
        name: Имя метода (``send_message``, ``edit_message_text``, ...).
        args: Позиционные аргументы вызова.
        kwargs: Именованные аргументы вызова.

    Returns:
        Однострочное описание вызова: адресат, текст, клавиатура.
    """
    if name == "answer_callback_query":
        query_id = args[0] if args else kwargs.get("callback_query_id")
        text = args[1] if len(args) > 1 else kwargs.get("text")
        return f"callback_query_id={query_id} text={_preview(text, 120)!r}"

    if name == "edit_message_text":
        text = args[0] if args else kwargs.get("text")
        chat_id = args[1] if len(args) > 1 else kwargs.get("chat_id")
        message_id = args[2] if len(args) > 2 else kwargs.get("message_id")
        return f"chat={chat_id} msg={message_id} text={_preview(text)!r}"

    if name == "edit_message_reply_markup":
        chat_id = args[0] if args else kwargs.get("chat_id")
        message_id = args[1] if len(args) > 1 else kwargs.get("message_id")
        markup = kwargs.get("reply_markup")
        state = "задана" if markup is not None else "убрана"
        return f"chat={chat_id} msg={message_id} markup={state}"

    if name == "reply_to":
        source = args[0] if args else kwargs.get("message")
        chat_id = getattr(getattr(source, "chat", None), "id", "?")
        text = args[1] if len(args) > 1 else kwargs.get("text")
        return f"chat={chat_id} text={_preview(text)!r}"

    # send_message и прочие методы с сигнатурой (chat_id, text, ...)
    chat_id = args[0] if args else kwargs.get("chat_id")
    text = args[1] if len(args) > 1 else kwargs.get("text")
    return f"chat={chat_id} text={_preview(text)!r}"


def _install_logging(bot: telebot.TeleBot) -> None:
    """Подключает сквозное логирование входящих апдейтов и ответов бота.

    Оборачивает ``process_new_updates`` (входящие сообщения и callback-запросы
    со состоянием FSM) и методы отправки сообщений, чтобы в ``bot.log``
    попадала полная картина диалога: что прислал пользователь, какой
    хендлер сработал и что ответил бот.

    Args:
        bot: Экземпляр ``TeleBot``.
    """
    # --- Входящие апдейты -------------------------------------------------
    original_process = bot.process_new_updates

    def process_with_logging(updates: list) -> Any:
        for update in updates or []:
            try:
                logger.info("ВХОД | %s", _describe_incoming(update))
            except Exception:  # noqa: BLE001 - описание не должно ронять polling
                logger.exception("Не удалось описать входящий апдейт")
        return original_process(updates)

    bot.process_new_updates = process_with_logging  # type: ignore[method-assign]

    # --- Исходящие ответы -------------------------------------------------
    for method_name in (
        "send_message",
        "reply_to",
        "edit_message_text",
        "edit_message_reply_markup",
        "answer_callback_query",
    ):
        original = getattr(bot, method_name, None)
        if original is None:
            continue
        bot.__dict__[method_name] = _wrap_outgoing(original, method_name)


def _wrap_outgoing(original: Any, name: str) -> Any:
    """Оборачивает метод отправки сообщения, добавляя запись в лог.

    Args:
        original: Исходный метод экземпляра ``TeleBot``.
        name: Имя метода для подписи в логе.

    Returns:
        Обёрнутый метод.
    """

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        description = _describe_outgoing(name, args, kwargs)
        try:
            result = original(*args, **kwargs)
        except Exception:
            logger.exception("ОШИБКА отправки %s | %s", name, description)
            raise
        logger.info("ОТВЕТ %s | %s", name, description)
        return result

    wrapper.__name__ = name
    return wrapper


def main() -> None:
    """Инициализирует приложение и запускает бота."""
    # 1) Конфигурация: падаем с понятной ошибкой, если .env неполный
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    # 2) Логирование: bot.log (INFO+) и bot_errors.log (ERROR+)
    setup_logging(settings)
    logger.info("Запуск бота «Мини-кошелёк путешественника»")

    # 3) База данных: создаём таблицы при первом запуске
    db.init_db(settings.db_path)

    # 4) Хендлеры
    bot = telebot.TeleBot(settings.telegram_bot_token, parse_mode="HTML")
    _install_logging(bot)
    register_handlers(bot)

    # 5) Long-polling
    #
    # allowed_updates указываем ЯВНО: Telegram запоминает последнюю заданную
    # настройку и при None продолжает фильтровать апдейты по ней. Если в
    # прошлый раз закрепился список без callback_query, все inline-кнопки
    # перестают доходить до бота — сообщения приходят, а нажатия нет.
    logger.info("Бот запущен, начинаем polling...")
    try:
        bot.infinity_polling(
            timeout=30,
            long_polling_timeout=30,
            skip_pending=True,
            allowed_updates=ALLOWED_UPDATES,
        )
    except (KeyboardInterrupt, SystemExit):
        logger.info("Остановка по сигналу пользователя")
    except Exception:
        logger.exception("Работа бота прервана непредвиденной ошибкой")
        raise


if __name__ == "__main__":
    main()
