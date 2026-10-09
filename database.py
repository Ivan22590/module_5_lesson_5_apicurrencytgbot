"""Работа с базой данных SQLite: инициализация схемы и CRUD-запросы.

Все запросы выполняются через параметризованные ``?``-плейсхолдеры,
каждый запрос, затрагивающий пользовательские данные, фильтруется
по ``telegram_id`` / ``user_id`` — пользователи изолированы друг от друга.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

SCHEMA_FILE = Path(__file__).resolve().parent / "schemas.sql"


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Открывает соединение с SQLite и включает режим foreign keys.

    Args:
        db_path: Путь к файлу базы данных.

    Returns:
        Соединение ``sqlite3`` с ``row_factory = sqlite3.Row``.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_session(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Контекстный менеджер: соединение всегда закрывается.

    ``with sqlite3.Connection`` фиксирует транзакцию, но **не закрывает**
    соединение — при многократном обращении файл базы удерживается
    открытым и локи SQLite могут «зависать». Здесь соединение закрывается
    гарантированно, даже при исключении.

    Args:
        db_path: Путь к файлу базы данных.

    Yields:
        Открытое соединение ``sqlite3``.
    """
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path) -> None:
    """Создаёт таблицы по схеме из ``schemas.sql``, если их ещё нет.

    Args:
        db_path: Путь к файлу базы данных.
    """
    schema_sql = SCHEMA_FILE.read_text(encoding="utf-8")
    with db_session(db_path) as conn:
        conn.executescript(schema_sql)
    logger.info("База данных инициализирована: %s", db_path)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def register_user(db_path: Path, telegram_id: int) -> None:
    """Регистрирует пользователя (идемпотентно).

    Args:
        db_path: Путь к файлу базы данных.
        telegram_id: Идентификатор пользователя в Telegram.
    """
    with db_session(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (telegram_id) VALUES (?)",
            (telegram_id,),
        )


# ---------------------------------------------------------------------------
# Trips
# ---------------------------------------------------------------------------

def create_trip(
    db_path: Path,
    user_id: int,
    title: str,
    from_country: str,
    to_country: str,
    from_currency: str,
    to_currency: str,
    rate: float,
    rate_manual: bool,
    initial_amount: float,
) -> int:
    """Создаёт новое путешествие и делает его активным.

    Одновременно все остальные путешествия пользователя деактивируются.

    Args:
        db_path: Путь к файлу базы данных.
        user_id: Telegram-id владельца.
        title: Название путешествия, например «Китай 2026».
        from_country: Страна отправления.
        to_country: Страна назначения.
        from_currency: Валюта домашняя (ISO 4217).
        to_currency: Валюта страны назначения (ISO 4217).
        rate: Курс from → to.
        rate_manual: ``True``, если курс введён вручную.
        initial_amount: Стартовая сумма в ``from_currency``.

    Returns:
        Идентификатор созданного путешествия.
    """
    with db_session(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (telegram_id) VALUES (?)",
            (user_id,),
        )
        conn.execute(
            "UPDATE trips SET is_active = FALSE WHERE user_id = ?",
            (user_id,),
        )
        cursor = conn.execute(
            """
            INSERT INTO trips (
                user_id, title, from_country, to_country,
                from_currency, to_currency, rate, rate_manual,
                initial_amount, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE)
            """,
            (
                user_id, title, from_country, to_country,
                from_currency, to_currency, rate,
                int(rate_manual), initial_amount,
            ),
        )
        trip_id = cursor.lastrowid
    logger.info(
        "Создано путешествие id=%s user=%s «%s» rate=%s",
        trip_id, user_id, title, rate,
    )
    return int(trip_id)


def get_active_trip(db_path: Path, user_id: int) -> sqlite3.Row | None:
    """Возвращает активное путешествие пользователя.

    Args:
        db_path: Путь к файлу базы данных.
        user_id: Telegram-id владельца.

    Returns:
        Строка путешествия или ``None``, если активного нет.
    """
    with db_session(db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM trips
            WHERE user_id = ? AND is_active = TRUE
            ORDER BY id DESC LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    return row


def get_trip(db_path: Path, trip_id: int, user_id: int) -> sqlite3.Row | None:
    """Возвращает путешествие, принадлежащее конкретному пользователю.

    Args:
        db_path: Путь к файлу базы данных.
        trip_id: Идентификатор путешествия.
        user_id: Telegram-id владельца.

    Returns:
        Строка путешествия или ``None``, если не найдено / чужое.
    """
    with db_session(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM trips WHERE id = ? AND user_id = ?",
            (trip_id, user_id),
        ).fetchone()
    return row


def get_trips(db_path: Path, user_id: int) -> list[sqlite3.Row]:
    """Возвращает все путешествия пользователя (новые сверху).

    Args:
        db_path: Путь к файлу базы данных.
        user_id: Telegram-id владельца.

    Returns:
        Список строк путешествий.
    """
    with db_session(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM trips
            WHERE user_id = ?
            ORDER BY is_active DESC, id DESC
            """,
            (user_id,),
        ).fetchall()
    return list(rows)


def set_active_trip(db_path: Path, user_id: int, trip_id: int) -> bool:
    """Делает путешествие активным, остальные — неактивными.

    Args:
        db_path: Путь к файлу базы данных.
        user_id: Telegram-id владельца.
        trip_id: Идентификатор выбираемого путешествия.

    Returns:
        ``True``, если путешествие найдено и активировано.
    """
    trip = get_trip(db_path, trip_id, user_id)
    if trip is None:
        return False
    with db_session(db_path) as conn:
        conn.execute(
            "UPDATE trips SET is_active = FALSE WHERE user_id = ?",
            (user_id,),
        )
        conn.execute(
            "UPDATE trips SET is_active = TRUE WHERE id = ? AND user_id = ?",
            (trip_id, user_id),
        )
    logger.info("Пользователь %s переключился на путешествие %s", user_id, trip_id)
    return True


def update_trip_rate(
    db_path: Path, user_id: int, trip_id: int, rate: float, manual: bool = True
) -> bool:
    """Обновляет курс путешествия (вручную заданный курс помечается).

    Args:
        db_path: Путь к файлу базы данных.
        user_id: Telegram-id владельца.
        trip_id: Идентификатор путешествия.
        rate: Новый курс from → to.
        manual: ``True`` — курс введён вручную.

    Returns:
        ``True``, если путешествие найдено и обновлено.
    """
    trip = get_trip(db_path, trip_id, user_id)
    if trip is None:
        return False
    with db_session(db_path) as conn:
        conn.execute(
            "UPDATE trips SET rate = ?, rate_manual = ? WHERE id = ? AND user_id = ?",
            (rate, int(manual), trip_id, user_id),
        )
    logger.info("Курс путешествия %s обновлён: %s (manual=%s)", trip_id, rate, manual)
    return True


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------

def add_expense(
    db_path: Path,
    trip_id: int,
    amount: float,
    amount_home: float,
    rate_used: float,
    category: str,
) -> int:
    """Добавляет расход в путешествие.

    Args:
        db_path: Путь к файлу базы данных.
        trip_id: Идентификатор путешествия.
        amount: Сумма в валюте страны назначения.
        amount_home: Пересчёт в домашнюю валюту.
        rate_used: Использованный курс.
        category: Категория расхода.

    Returns:
        Идентификатор созданного расхода.
    """
    with db_session(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO expenses (trip_id, amount, amount_home, rate_used, category)
            VALUES (?, ?, ?, ?, ?)
            """,
            (trip_id, amount, amount_home, rate_used, category),
        )
        expense_id = cursor.lastrowid
    logger.info(
        "Расход id=%s trip=%s: %s (home=%s) [%s]",
        expense_id, trip_id, amount, amount_home, category,
    )
    return int(expense_id)


def get_expenses_page(
    db_path: Path, user_id: int, trip_id: int, limit: int, offset: int
) -> list[sqlite3.Row]:
    """Возвращает страницу расходов путешествия пользователя.

    Args:
        db_path: Путь к файлу базы данных.
        user_id: Telegram-id владельца (изоляция данных).
        trip_id: Идентификатор путешествия.
        limit: Максимум записей.
        offset: Смещение.

    Returns:
        Список строк расходов (новые сверху).
    """
    with db_session(db_path) as conn:
        rows = conn.execute(
            """
            SELECT e.* FROM expenses e
            JOIN trips t ON t.id = e.trip_id
            WHERE e.trip_id = ? AND t.user_id = ?
            ORDER BY e.id DESC
            LIMIT ? OFFSET ?
            """,
            (trip_id, user_id, limit, offset),
        ).fetchall()
    return list(rows)


def get_expense_totals(db_path: Path, user_id: int, trip_id: int) -> dict[str, float]:
    """Возвращает суммарные расходы путешествия в обеих валютах.

    Args:
        db_path: Путь к файлу базы данных.
        user_id: Telegram-id владельца (изоляция данных).
        trip_id: Идентификатор путешествия.

    Returns:
        Словарь с ключами ``count``, ``amount``, ``amount_home``.
    """
    with db_session(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt,
                   COALESCE(SUM(e.amount), 0) AS total,
                   COALESCE(SUM(e.amount_home), 0) AS total_home
            FROM expenses e
            JOIN trips t ON t.id = e.trip_id
            WHERE e.trip_id = ? AND t.user_id = ?
            """,
            (trip_id, user_id),
        ).fetchone()
    return {
        "count": float(row["cnt"]),
        "amount": float(row["total"]),
        "amount_home": float(row["total_home"]),
    }


def get_balance(db_path: Path, user_id: int) -> dict[str, Any] | None:
    """Считает остаток активного путешествия в обеих валютах.

    Args:
        db_path: Путь к файлу базы данных.
        user_id: Telegram-id владельца.

    Returns:
        Словарь с ключами ``trip``, ``balance_home``, ``balance_dest``,
        ``spent_home``, ``spent_dest``; ``None``, если активного
        путешествия нет.
    """
    trip = get_active_trip(db_path, user_id)
    if trip is None:
        return None
    return compute_trip_balance(db_path, user_id, trip)


def get_trip_balance(
    db_path: Path, user_id: int, trip_id: int
) -> dict[str, Any] | None:
    """Считает остаток указанного путешествия пользователя.

    Args:
        db_path: Путь к файлу базы данных.
        user_id: Telegram-id владельца (изоляция данных).
        trip_id: Идентификатор путешествия.

    Returns:
        Словарь баланса или ``None``, если путешествие не найдено.
    """
    trip = get_trip(db_path, trip_id, user_id)
    if trip is None:
        return None
    return compute_trip_balance(db_path, user_id, trip)


def compute_trip_balance(
    db_path: Path, user_id: int, trip: sqlite3.Row
) -> dict[str, Any]:
    """Считает остаток переданного путешествия в обеих валютах.

    Args:
        db_path: Путь к файлу базы данных.
        user_id: Telegram-id владельца.
        trip: Строка путешествия.

    Returns:
        Словарь с ключами ``trip``, ``balance_home``, ``balance_dest``,
        ``spent_home``, ``spent_dest``, ``expense_count``.
    """
    totals = get_expense_totals(db_path, user_id, int(trip["id"]))
    spent_home = totals["amount_home"]
    rate = float(trip["rate"])
    balance_home = float(trip["initial_amount"]) - spent_home
    balance_dest = balance_home * rate if rate else 0.0
    spent_dest = totals["amount"] if rate else 0.0

    return {
        "trip": trip,
        "balance_home": balance_home,
        "balance_dest": balance_dest,
        "spent_home": spent_home,
        "spent_dest": spent_dest,
        "expense_count": int(totals["count"]),
    }
