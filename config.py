"""Конфигурация бота: загрузка переменных окружения и общие константы.

Модуль отвечает за чтение ``.env``-файла, валидацию обязательных
переменных окружения при старте и предоставление настроек в виде
неизменяемого объекта :class:`Settings`.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Пути
# ---------------------------------------------------------------------------

BASE_DIR: Path = Path(__file__).resolve().parent

# Пути к файлам приложения
DB_PATH: Path = BASE_DIR / "wallet.db"
LOG_PATH: Path = BASE_DIR / "bot.log"
ERROR_LOG_PATH: Path = BASE_DIR / "bot_errors.log"

# Загружаем .env до обращения к os.environ
load_dotenv(BASE_DIR / ".env")


class ConfigError(RuntimeError):
    """Исключение ошибки конфигурации (отсутствуют переменные окружения)."""


def _require(name: str, errors: list[str]) -> str:
    """Возвращает значение переменной окружения или добавляет ошибку.

    Args:
        name: Имя переменной окружения.
        errors: Список, куда добавляется описание проблемы.

    Returns:
        Значение переменной или пустая строка (если переменной нет).
    """
    value = os.getenv(name, "").strip()
    if not value:
        errors.append(f"  - {name} не задана")
    return value


@dataclass(frozen=True)
class Settings:
    """Неизменяемые настройки приложения.

    Attributes:
        telegram_bot_token: Токен Telegram-бота от @BotFather.
        currency_api_key: API-ключ сервиса api.exchangerate.host.
        db_path: Путь к файлу SQLite-базы данных.
        log_path: Путь к основному файлу логов.
        error_log_path: Путь к файлу логов ошибок.
        rate_cache_ttl: Время жизни кеша курсов в секундах.
    """

    telegram_bot_token: str
    currency_api_key: str
    db_path: Path = DB_PATH
    log_path: Path = LOG_PATH
    error_log_path: Path = ERROR_LOG_PATH
    rate_cache_ttl: int = 3600  # 1 час


def load_settings() -> Settings:
    """Загружает и валидирует настройки из переменных окружения.

    Returns:
        Заполненный объект :class:`Settings`.

    Raises:
        ConfigError: Если одна или несколько обязательных переменных
            окружения отсутствуют.
    """
    errors: list[str] = []

    bot_token = _require("TELEGRAM_BOT_TOKEN", errors)
    api_key = _require("CURRENCY_API_KEY", errors)

    if errors:
        message = (
            "Ошибка конфигурации. Отсутствуют переменные окружения:\n"
            + "\n".join(errors)
            + "\n\nСоздайте файл .env (см. .env.example) и заполните значения."
        )
        raise ConfigError(message)

    return Settings(
        telegram_bot_token=bot_token,
        currency_api_key=api_key,
    )


def setup_logging(settings: Settings) -> logging.Logger:
    """Настраивает логирование в файлы и консоль.

    Основной лог ``bot.log`` записывает сообщения уровня INFO и выше,
    файл ``bot_errors.log`` — только ошибки (ERROR и выше) с трейсбеками.

    Args:
        settings: Настройки приложения (пути к логам).

    Returns:
        Корневой логгер приложения.
    """
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Очищаем обработчики при повторной настройке (защита от дублей)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 1) Основной файл: INFO и выше
    file_handler = logging.FileHandler(settings.log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 2) Файл ошибок: только ERROR и выше (ошибки отдельно)
    error_handler = logging.FileHandler(settings.error_log_path, encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)

    # 3) Консоль: WARNING и выше
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger
