"""FSM-состояния пользователя (in-memory, аналог user_data в aiogram).

pyTelegramBotAPI не имеет встроенного FSM, поэтому состояния хранятся
в словарях ``{user_id: state}`` и ``{user_id: data}`` на время работы
процесса. Данные текущего шага (черновик путешествия, ожидаемая трата)
хранятся в :func:`user_data`.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class State(str, Enum):
    """Состояния конечного автомата пользователя."""

    IDLE = "idle"                          # главное меню, ожидание действия
    TRIP_FROM = "trip_from"                # ожидание страны отправления
    TRIP_TO = "trip_to"                    # ожидание страны назначения
    TRIP_RATE_CONFIRM = "trip_rate_confirm"  # подтверждение полученного курса
    TRIP_MANUAL_RATE = "trip_manual_rate"  # ожидание ручного курса
    TRIP_AMOUNT = "trip_amount"            # ожидание стартовой суммы
    EXPENSE_CATEGORY = "expense_category"  # выбор категории расхода
    EXPENSE_CONFIRM = "expense_confirm"    # подтверждение расхода
    RATE_EDIT = "rate_edit"                # ожидание нового курса (/setrate)


# Текущее состояние каждого пользователя
_states: dict[int, State] = {}

# Данные FSM (аналог user_data): черновик путешествия, сумма расхода и т.п.
_data: dict[int, dict[str, Any]] = {}


def get_state(user_id: int) -> State:
    """Возвращает текущее состояние пользователя.

    Args:
        user_id: Telegram-id пользователя.

    Returns:
        Текущее состояние, по умолчанию :attr:`State.IDLE`.
    """
    return _states.get(user_id, State.IDLE)


def set_state(user_id: int, state: State) -> None:
    """Устанавливает состояние пользователя.

    Args:
        user_id: Telegram-id пользователя.
        state: Новое состояние.
    """
    _states[user_id] = state


def reset_state(user_id: int) -> None:
    """Сбрасывает состояние в :attr:`State.IDLE` и очищает FSM-данные.

    Args:
        user_id: Telegram-id пользователя.
    """
    _states[user_id] = State.IDLE
    _data.pop(user_id, None)


def user_data(user_id: int) -> dict[str, Any]:
    """Возвращает словарь FSM-данных пользователя (создаёт при отсутствии).

    Args:
        user_id: Telegram-id пользователя.

    Returns:
        Словарь данных текущего шага.
    """
    return _data.setdefault(user_id, {})
