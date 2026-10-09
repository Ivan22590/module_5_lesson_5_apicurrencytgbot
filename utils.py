"""Утилиты: форматирование валют и дат, валидация ввода, безопасные хендлеры."""

from __future__ import annotations

import functools
import logging
import re
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Эмодзи и символы валют
# ---------------------------------------------------------------------------

CURRENCY_SYMBOLS: dict[str, str] = {
    "RUB": "₽", "EUR": "€", "USD": "$", "JPY": "¥", "KRW": "₩",
    "GBP": "£", "TRY": "₺", "KZT": "₸", "UAH": "₴",
    "BYN": "Br", "AMD": "֏", "GEL": "₾", "AZN": "₼", "INR": "₹",
    "THB": "฿", "VND": "₫", "IDR": "Rp", "ILS": "₪", "PHP": "₱",
    # CNY намеренно без символа (¥ общий с JPY) — по ТЗ используется код "CNY"
}

# Категории расходов: ключ → (эмодзи, название)
CATEGORIES: dict[str, tuple[str, str]] = {
    "food": ("🍽", "Еда"),
    "hotel": ("🏨", "Проживание"),
    "transport": ("🚕", "Транспорт"),
    "fun": ("🎭", "Развлечения"),
    "shopping": ("🛍", "Покупки"),
    "other": ("📌", "Прочее"),
}


# ---------------------------------------------------------------------------
# Форматирование
# ---------------------------------------------------------------------------

def format_number(value: float) -> str:
    """Форматирует число с разделителем тысяч и без лишних нулей.

    Args:
        value: Число.

    Returns:
        Строка вида ``"200 000"``, ``"1 923.07"``, ``"50"``.
    """
    rounded = round(float(value), 2)
    if rounded == int(rounded):
        return f"{int(rounded):,}".replace(",", " ")
    text = f"{rounded:,.2f}".replace(",", " ")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def format_money(value: float, currency: str) -> str:
    """Форматирует сумму с символом валюты.

    Суммы от 1000 показываются целыми (как в примерах ТЗ: «1 923 €»),
    меньшие — с точностью до копейки без лишних нулей.
    Для валют без символа используется код ISO.

    Args:
        value: Сумма.
        currency: Код валюты ISO 4217.

    Returns:
        Строка вида ``"1 280 ₽"`` или ``"100 CNY"``.
    """
    currency = currency.upper()
    symbol = CURRENCY_SYMBOLS.get(currency, currency)
    if abs(float(value)) >= 1000:
        shown = f"{round(float(value)):,}".replace(",", " ")
    else:
        shown = format_number(value)
    return f"{shown} {symbol}"


def format_rate_display(rate: float, from_currency: str, to_currency: str) -> str:
    """Форматирует курс в человекочитаемом виде «1 to = X from».

    ``rate`` хранится как from → to (1 from = rate to), поэтому
    отображаемая величина — обратная (1 to = 1/rate from).

    Args:
        rate: Курс from → to.
        from_currency: Домашняя валюта (ISO 4217).
        to_currency: Валюта страны назначения (ISO 4217).

    Returns:
        Строка вида ``"1 EUR = 104 RUB"``.
    """
    if not rate:
        return f"1 {to_currency.upper()} = ? {from_currency.upper()}"
    inverse = 1.0 / rate
    return (
        f"1 {to_currency.upper()} = {format_number(inverse)} "
        f"{from_currency.upper()}"
    )


def parse_amount(text: str) -> float | None:
    """Разбирает пользовательский ввод как положительное число.

    Поддерживает запятую и точку в качестве разделителя, пробелы
    в качестве разделителя тысяч.

    Args:
        text: Строка от пользователя.

    Returns:
        Число или ``None``, если это не число.
    """
    if text is None:
        return None
    cleaned = text.strip().replace("\u00a0", " ").replace(" ", "")
    cleaned = cleaned.replace(",", ".")
    if not re.fullmatch(r"-?\d+(\.\d+)?", cleaned):
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 0 else None


def format_date(value: str | None) -> str:
    """Форматирует дату из SQLite в ``dd.mm.yyyy HH:MM``.

    Args:
        value: Строка даты (``TIMESTAMP``) или ``None``.

    Returns:
        Отформатированная дата или пустая строка.
    """
    if not value:
        return ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            dt = datetime.strptime(str(value)[:19], fmt)
            return dt.strftime("%d.%m.%Y %H:%M")
        except ValueError:
            continue
    return str(value)


def category_emoji(category: str) -> str:
    """Возвращает эмодзи для категории расхода.

    Args:
        category: Название категории.

    Returns:
        Эмодзи категории или 📌 по умолчанию.
    """
    for _key, (emoji, label) in CATEGORIES.items():
        if label.lower() == str(category).lower():
            return emoji
    return "📌"


# ---------------------------------------------------------------------------
# Безопасная обёртка для хендлеров
# ---------------------------------------------------------------------------

def safe_handler(func: Callable[..., Any]) -> Callable[..., Any]:
    """Оборачивает хендлер в try/except с логированием и ответом пользователю.

    Хендлер должен быть зарегистрирован с ``pass_bot=True``, чтобы
    объект бота приходил в ``kwargs['bot']``.

    Args:
        func: Исходный хендлер telebot.

    Returns:
        Обёрнутый хендлер.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception:  # noqa: BLE001 - перехватываем всё по ТЗ
            logger.exception("Необработанное исключение в %s", func.__name__)
            _notify_error(args, kwargs.get("bot"))
            return None

    return wrapper


def _notify_error(args: Any, bot: Any) -> None:
    """Отправляет пользователю дружелюбное сообщение об ошибке.

    Args:
        args: Позиционные аргументы хендлера (сообщение или callback).
        bot: Экземпляр ``TeleBot`` (может быть ``None``).
    """
    if bot is None or not args:
        return
    try:
        chat_id = _extract_chat_id(args[0])
        if chat_id is not None:
            bot.send_message(
                chat_id,
                "⚠️ Произошла непредвиденная ошибка. Попробуйте ещё раз.",
            )
    except Exception:  # noqa: BLE001 - не роняем бота из-за ошибки уведомления
        logger.exception("Не удалось отправить сообщение об ошибке")


def _extract_chat_id(obj: Any) -> int | None:
    """Извлекает chat_id из сообщения или callback-запроса.

    Args:
        obj: Сообщение ``types.Message`` или ``types.CallbackQuery``.

    Returns:
        chat_id или ``None``.
    """
    chat = getattr(obj, "chat", None)
    if chat is not None and hasattr(chat, "id"):
        return int(chat.id)
    message = getattr(obj, "message", None)
    if message is not None:
        chat = getattr(message, "chat", None)
        if chat is not None and hasattr(chat, "id"):
            return int(chat.id)
    return None
