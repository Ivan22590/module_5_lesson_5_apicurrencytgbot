"""Хендлеры путешествий: создание (FSM), переключение, изменение курса."""

from __future__ import annotations

import html
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from telebot import types

import currency_api
import database as db
import keyboards
from config import DB_PATH
from currency_api import ApiError, CurrencyNotFoundError
from states import State, get_state, reset_state, set_state, user_data
from utils import format_money, format_rate_display, parse_amount, safe_handler

if TYPE_CHECKING:
    import telebot

logger = logging.getLogger(__name__)

API_ERROR_TEXT = "Сервис курсов временно недоступен, попробуйте позже."
UNKNOWN_COUNTRY_TEXT = (
    "Не удалось определить валюту для этой страны. Проверьте название."
)
NOT_A_NUMBER_TEXT = "Пожалуйста, отправьте число"


# ---------------------------------------------------------------------------
# Начало создания путешествия
# ---------------------------------------------------------------------------

def begin_trip_creation(bot: "telebot.TeleBot", message: types.Message) -> None:
    """Начинает FSM создания путешествия: просит страну отправления.

    Args:
        bot: Экземпляр ``TeleBot``.
        message: Сообщение пользователя.
    """
    user_id = message.from_user.id
    reset_state(user_id)
    set_state(user_id, State.TRIP_FROM)
    bot.send_message(
        message.chat.id,
        "🌍 <b>Создание путешествия</b>\n\n"
        "Шаг 1/4. Введите <b>страну отправления</b> текстом "
        "или выберите из списка:",
        parse_mode="HTML",
        reply_markup=keyboards.popular_countries("from"),
    )


def _resolve_country(raw: str, from_button: bool) -> tuple[str, str]:
    """Определяет название страны и её валюту по вводу пользователя.

    Args:
        raw: Текст пользователя либо ISO-код страны (кнопка).
        from_button: ``True``, если ввод пришёл из inline-кнопки.

    Returns:
        Кортеж (название страны, код валюты ISO 4217).

    Raises:
        CurrencyNotFoundError: Если страна не распознана.
    """
    if from_button:
        display = keyboards.country_display(raw)
        plain = display.split(" ", 1)[-1] if " " in display else display
    else:
        plain = raw.strip()
    currency = currency_api.get_currency_by_country(raw if from_button else plain)
    return plain, currency


def handle_from_country(
    bot: "telebot.TeleBot", chat_id: int, user_id: int, raw: str,
    from_button: bool = False,
) -> None:
    """Обрабатывает ввод страны отправления (шаг 1/4).

    Args:
        bot: Экземпляр ``TeleBot``.
        chat_id: Идентификатор чата.
        user_id: Telegram-id пользователя.
        raw: Введённый текст или ISO-код страны.
        from_button: ``True``, если страна выбрана inline-кнопкой.
    """
    try:
        country, currency = _resolve_country(raw, from_button)
    except CurrencyNotFoundError:
        bot.send_message(chat_id, UNKNOWN_COUNTRY_TEXT)
        return  # состояние не меняем — просим ввести заново

    data = user_data(user_id)
    data.clear()
    data.update(from_country=country, from_currency=currency)
    set_state(user_id, State.TRIP_TO)

    bot.send_message(
        chat_id,
        f"🏠 Страна отправления: <b>{html.escape(country)}</b> "
        f"(валюта: {currency})\n\n"
        "Шаг 2/4. Введите <b>страну назначения</b> текстом "
        "или выберите из списка:",
        parse_mode="HTML",
        reply_markup=keyboards.popular_countries("to"),
    )


def handle_to_country(
    bot: "telebot.TeleBot", chat_id: int, user_id: int, raw: str,
    from_button: bool = False,
) -> None:
    """Обрабатывает ввод страны назначения и запрашивает курс (шаг 2/4).

    Args:
        bot: Экземпляр ``TeleBot``.
        chat_id: Идентификатор чата.
        user_id: Telegram-id пользователя.
        raw: Введённый текст или ISO-код страны.
        from_button: ``True``, если страна выбрана inline-кнопкой.
    """
    try:
        country, currency = _resolve_country(raw, from_button)
    except CurrencyNotFoundError:
        bot.send_message(chat_id, UNKNOWN_COUNTRY_TEXT)
        return

    data = user_data(user_id)
    from_currency = data.get("from_currency", "")
    if currency == from_currency:
        bot.send_message(
            chat_id,
            "Валюта назначения совпадает с домашней. Выберите другую страну.",
        )
        return

    data.update(to_country=country, to_currency=currency)

    try:
        rate = currency_api.get_exchange_rate(from_currency, currency)
    except ApiError:
        logger.warning("Не удалось получить курс %s→%s", from_currency, currency)
        data["rate_manual"] = True
        set_state(user_id, State.TRIP_MANUAL_RATE)
        bot.send_message(
            chat_id,
            f"{API_ERROR_TEXT}\n\n"
            "Введите курс вручную в формате:\n"
            f"<b>1 {currency} = ___ {from_currency}</b>",
            parse_mode="HTML",
        )
        return

    data.update(rate=rate, rate_manual=False)
    set_state(user_id, State.TRIP_RATE_CONFIRM)
    bot.send_message(
        chat_id,
        f"Курс: <b>{format_rate_display(rate, from_currency, currency)}</b>\n\n"
        "Подтвердить?",
        parse_mode="HTML",
        reply_markup=keyboards.rate_confirmation(),
    )


def confirm_rate_yes(bot: "telebot.TeleBot", chat_id: int, user_id: int) -> None:
    """Подтверждает курс и просит стартовую сумму (шаг 3/4 → 4/4).

    Args:
        bot: Экземпляр ``TeleBot``.
        chat_id: Идентификатор чата.
        user_id: Telegram-id пользователя.
    """
    if get_state(user_id) != State.TRIP_RATE_CONFIRM:
        bot.send_message(chat_id, "Сначала создайте путешествие.")
        return
    data = user_data(user_id)
    set_state(user_id, State.TRIP_AMOUNT)
    bot.send_message(
        chat_id,
        "Шаг 4/4. Введите <b>стартовую сумму</b> в домашней валюте "
        f"({data.get('from_currency', 'RUB')}):",
        parse_mode="HTML",
    )


def confirm_rate_no(bot: "telebot.TeleBot", chat_id: int, user_id: int) -> None:
    """Отклоняет API-курс и просит ввести курс вручную.

    Args:
        bot: Экземпляр ``TeleBot``.
        chat_id: Идентификатор чата.
        user_id: Telegram-id пользователя.
    """
    if get_state(user_id) != State.TRIP_RATE_CONFIRM:
        bot.send_message(chat_id, "Сначала создайте путешествие.")
        return
    data = user_data(user_id)
    set_state(user_id, State.TRIP_MANUAL_RATE)
    bot.send_message(
        chat_id,
        "Введите курс вручную в формате:\n"
        f"<b>1 {data.get('to_currency', 'EUR')} = ___ "
        f"{data.get('from_currency', 'RUB')}</b>\n\n"
        "Например: <code>104</code>",
        parse_mode="HTML",
    )


def handle_manual_rate(
    bot: "telebot.TeleBot", chat_id: int, user_id: int, text: str
) -> None:
    """Принимает ручной курс и переходит к стартовой сумме.

    Пользователь вводит курс в отображаемом виде (``1 to = X from``),
    поэтому сохранённый ``rate`` (from → to) равен ``1 / X``.

    Args:
        bot: Экземпляр ``TeleBot``.
        chat_id: Идентификатор чата.
        user_id: Telegram-id пользователя.
        text: Введённое сообщение.
    """
    value = parse_amount(text)
    if value is None:
        bot.send_message(chat_id, NOT_A_NUMBER_TEXT)
        return

    data = user_data(user_id)
    data.update(rate=1.0 / value, rate_manual=True)
    set_state(user_id, State.TRIP_AMOUNT)
    bot.send_message(
        chat_id,
        "Шаг 4/4. Введите <b>стартовую сумму</b> в домашней валюте "
        f"({data.get('from_currency', 'RUB')}):",
        parse_mode="HTML",
    )


def handle_initial_amount(
    bot: "telebot.TeleBot", chat_id: int, user_id: int, text: str
) -> None:
    """Принимает стартовую сумму и создаёт путешествие.

    Args:
        bot: Экземпляр ``TeleBot``.
        chat_id: Идентификатор чата.
        user_id: Telegram-id пользователя.
        text: Введённое сообщение.
    """
    amount = parse_amount(text)
    if amount is None:
        bot.send_message(chat_id, NOT_A_NUMBER_TEXT)
        return

    data = user_data(user_id)
    required = ("from_country", "to_country", "from_currency", "to_currency", "rate")
    if any(key not in data for key in required):
        logger.error("Неполные данные FSM у пользователя %s: %s", user_id, data)
        reset_state(user_id)
        bot.send_message(
            chat_id,
            "Что-то пошло не так при создании путешествия. "
            "Нажмите «🆕 Создать путешествие» ещё раз.",
        )
        return

    year = datetime.now().year
    title = f"{data['to_country']} {year}"

    trip_id = db.create_trip(
        DB_PATH,
        user_id,
        title,
        data["from_country"],
        data["to_country"],
        data["from_currency"],
        data["to_currency"],
        float(data["rate"]),
        bool(data.get("rate_manual", False)),
        amount,
    )
    rate = float(data["rate"])
    dest_amount = amount * rate
    rate_note = "вручную" if data.get("rate_manual") else "API"
    reset_state(user_id)

    logger.info("Пользователь %s создал путешествие %s", user_id, trip_id)
    bot.send_message(
        chat_id,
        f"✅ Путешествие <b>«{html.escape(title)}»</b> создано!\n\n"
        f"Баланс: {format_money(amount, data['from_currency'])} ≈ "
        f"{format_money(dest_amount, data['to_currency'])}\n"
        f"Курс: {format_rate_display(rate, data['from_currency'], data['to_currency'])}"
        f" ({rate_note})\n\n"
        "Отправляйте любое число — я запишу расход 💸",
        parse_mode="HTML",
        reply_markup=keyboards.main_menu(),
    )


# ---------------------------------------------------------------------------
# Список и переключение путешествий
# ---------------------------------------------------------------------------

def show_trip_list(
    bot: "telebot.TeleBot", chat_id: int, user_id: int,
    message_id: int | None = None,
) -> None:
    """Показывает список путешествий с inline-кнопками переключения.

    Args:
        bot: Экземпляр ``TeleBot``.
        chat_id: Идентификатор чата.
        user_id: Telegram-id пользователя.
        message_id: Идентификатор сообщения для редактирования.
    """
    trips = db.get_trips(DB_PATH, user_id)
    if not trips:
        text = (
            "📂 У вас пока нет путешествий.\n"
            "Нажмите «🆕 Создать путешествие»."
        )
        markup = keyboards.back_to_menu()
    else:
        lines = ["📂 <b>Ваши путешествия</b>\n"]
        for trip in trips:
            marker = "🟢" if trip["is_active"] else "⚪"
            balance = db.get_trip_balance(DB_PATH, user_id, int(trip["id"]))
            dest_text = ""
            if balance is not None:
                dest_text = (
                    f" / {format_money(float(balance['balance_dest']), str(trip['to_currency']))}"
                )
            balance_home = (
                float(balance["balance_home"]) if balance is not None
                else float(trip["initial_amount"])
            )
            lines.append(
                f"{marker} <b>{html.escape(str(trip['title']))}</b>\n"
                f"   {trip['from_currency']} → {trip['to_currency']}, "
                f"остаток {format_money(balance_home, str(trip['from_currency']))}"
                f"{dest_text}"
            )
        lines.append("\nНажмите, чтобы переключиться 👇")
        text = "\n".join(lines)
        markup = keyboards.trips_list(trips)

    if message_id is not None:
        try:
            bot.edit_message_text(
                text, chat_id, message_id, parse_mode="HTML", reply_markup=markup
            )
        except Exception as exc:  # noqa: BLE001 - «message is not modified» и т.п.
            # Telegram бросает ошибку, если текст не изменился (например,
            # пользователь нажал на уже активное путешествие). Это не сбой.
            logger.debug("edit_message_text не выполнен: %s", exc)
    else:
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)


def switch_trip(bot: "telebot.TeleBot", call: types.CallbackQuery, trip_id: int) -> None:
    """Делает выбранное путешествие активным.

    Args:
        bot: Экземпляр ``TeleBot``.
        call: Callback-запрос.
        trip_id: Идентификатор выбираемого путешествия.
    """
    user_id = call.from_user.id
    chat_id = call.message.chat.id if call.message else None
    message_id = call.message.message_id if call.message else None
    if chat_id is None or message_id is None:
        return

    if not db.set_active_trip(DB_PATH, user_id, trip_id):
        bot.answer_callback_query(call.id, "Путешествие не найдено", show_alert=True)
        return

    reset_state(user_id)
    bot.answer_callback_query(call.id, "Путешествие переключено ✅")
    show_trip_list(bot, chat_id, user_id, message_id=message_id)


# ---------------------------------------------------------------------------
# Изменение курса (/setrate)
# ---------------------------------------------------------------------------

def begin_rate_edit(bot: "telebot.TeleBot", message: types.Message) -> None:
    """Просит ввести новый курс для активного путешествия.

    Args:
        bot: Экземпляр ``TeleBot``.
        message: Сообщение пользователя.
    """
    user_id = message.from_user.id
    trip = db.get_active_trip(DB_PATH, user_id)
    if trip is None:
        bot.send_message(
            message.chat.id,
            "Нет активного путешествия. Создайте его кнопкой "
            "«🆕 Создать путешествие» или выберите «📂 Мои путешествия».",
        )
        return

    reset_state(user_id)
    set_state(user_id, State.RATE_EDIT)
    rate = float(trip["rate"])
    note = "вручную" if trip["rate_manual"] else "API"
    bot.send_message(
        message.chat.id,
        f"⚙️ Текущий курс <b>«{html.escape(str(trip['title']))}»</b>:\n"
        f"{format_rate_display(rate, str(trip['from_currency']), str(trip['to_currency']))}"
        f" ({note})\n\n"
        "Введите новый курс в формате:\n"
        f"<b>1 {trip['to_currency']} = ___ {trip['from_currency']}</b>",
        parse_mode="HTML",
    )


def handle_rate_edit(
    bot: "telebot.TeleBot", chat_id: int, user_id: int, text: str
) -> None:
    """Принимает новый курс и сохраняет его (rate_manual = TRUE).

    Args:
        bot: Экземпляр ``TeleBot``.
        chat_id: Идентификатор чата.
        user_id: Telegram-id пользователя.
        text: Введённое сообщение.
    """
    value = parse_amount(text)
    if value is None:
        bot.send_message(chat_id, NOT_A_NUMBER_TEXT)
        return

    trip = db.get_active_trip(DB_PATH, user_id)
    if trip is None:
        reset_state(user_id)
        bot.send_message(chat_id, "Активное путешествие не найдено.")
        return

    rate = 1.0 / value
    db.update_trip_rate(DB_PATH, user_id, int(trip["id"]), rate, manual=True)
    reset_state(user_id)

    balance = db.get_balance(DB_PATH, user_id)
    lines = [
        "✅ Курс обновлён:",
        format_rate_display(rate, str(trip["from_currency"]), str(trip["to_currency"])),
        "",
    ]
    if balance is not None:
        lines.append(
            f"Баланс: {format_money(float(balance['balance_dest']), str(trip['to_currency']))}"
            f" ≈ {format_money(float(balance['balance_home']), str(trip['from_currency']))}"
        )
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Регистрация хендлеров
# ---------------------------------------------------------------------------

def register(bot: "telebot.TeleBot") -> None:
    """Регистрирует FSM-хендлеры создания путешествия и изменения курса.

    Args:
        bot: Экземпляр ``TeleBot``.
    """

    @bot.message_handler(
        func=lambda m: get_state(m.from_user.id) == State.TRIP_FROM,
        pass_bot=True,
    )
    @safe_handler
    def fsm_trip_from(message: types.Message, bot: "telebot.TeleBot | None" = None) -> None:
        """Шаг 1/4 — страна отправления."""
        assert bot is not None
        handle_from_country(bot, message.chat.id, message.from_user.id, message.text or "")

    @bot.message_handler(
        func=lambda m: get_state(m.from_user.id) == State.TRIP_TO,
        pass_bot=True,
    )
    @safe_handler
    def fsm_trip_to(message: types.Message, bot: "telebot.TeleBot | None" = None) -> None:
        """Шаг 2/4 — страна назначения."""
        assert bot is not None
        handle_to_country(bot, message.chat.id, message.from_user.id, message.text or "")

    @bot.message_handler(
        func=lambda m: get_state(m.from_user.id) == State.TRIP_MANUAL_RATE,
        pass_bot=True,
    )
    @safe_handler
    def fsm_manual_rate(message: types.Message, bot: "telebot.TeleBot | None" = None) -> None:
        """Ручной курс путешествия."""
        assert bot is not None
        handle_manual_rate(bot, message.chat.id, message.from_user.id, message.text or "")

    @bot.message_handler(
        func=lambda m: get_state(m.from_user.id) == State.TRIP_RATE_CONFIRM,
        pass_bot=True,
    )
    @safe_handler
    def fsm_rate_confirm(message: types.Message, bot: "telebot.TeleBot | None" = None) -> None:
        """Просит подтвердить курс кнопками, если пришёл обычный текст."""
        assert bot is not None
        bot.send_message(
            message.chat.id,
            "Пожалуйста, подтвердите курс кнопками «✅ Да» или «❌ Нет» "
            "под предыдущим сообщением.",
        )

    @bot.message_handler(
        func=lambda m: get_state(m.from_user.id) == State.TRIP_AMOUNT,
        pass_bot=True,
    )
    @safe_handler
    def fsm_initial_amount(message: types.Message, bot: "telebot.TeleBot | None" = None) -> None:
        """Шаг 4/4 — стартовая сумма."""
        assert bot is not None
        handle_initial_amount(bot, message.chat.id, message.from_user.id, message.text or "")

    @bot.message_handler(
        func=lambda m: get_state(m.from_user.id) == State.RATE_EDIT,
        pass_bot=True,
    )
    @safe_handler
    def fsm_rate_edit(message: types.Message, bot: "telebot.TeleBot | None" = None) -> None:
        """Ручной ввод нового курса (/setrate)."""
        assert bot is not None
        handle_rate_edit(bot, message.chat.id, message.from_user.id, message.text or "")
