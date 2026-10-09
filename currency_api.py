"""Модуль для работы с API курсов https://api.exchangerate.host.

Предоставляет три публичные функции:

* :func:`get_currency_by_country` — определение валюты по стране (ISO);
* :func:`get_exchange_rate` — получение актуального курса с кешем TTL 1 час;
* :func:`convert_amount` — конвертация суммы с учётом кеша.

Все ошибки API обёрнуты в кастомные исключения :class:`ApiError` и
:class:`CurrencyNotFoundError`, которые перехватываются в хендлерах.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Final

import requests
from cachetools import TTLCache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Исключения модуля
# ---------------------------------------------------------------------------

class CurrencyNotFoundError(Exception):
    """Не удалось определить валюту для указанной страны."""


class ApiError(Exception):
    """Ошибка обращения к сервису курсов (сеть, лимит, некорректный ответ)."""


# ---------------------------------------------------------------------------
# Статический словарь ISO 3166 → ISO 4217 (fallback, эндпоинта нет в API)
# ---------------------------------------------------------------------------

COUNTRY_CURRENCY: Final[dict[str, str]] = {
    # Еврозона
    "DE": "EUR", "IT": "EUR", "ES": "EUR", "FR": "EUR", "PT": "EUR",
    "GR": "EUR", "NL": "EUR", "AT": "EUR", "BE": "EUR", "IE": "EUR",
    "FI": "EUR", "SK": "EUR", "SI": "EUR", "LT": "EUR", "LV": "EUR",
    "EE": "EUR", "LU": "EUR", "HR": "EUR", "CY": "EUR", "MT": "EUR",
    "ME": "EUR",
    # СНГ и соседи
    "RU": "RUB", "BY": "BYN", "UA": "UAH", "KZ": "KZT", "UZ": "UZS",
    "KG": "KGS", "TJ": "TJS", "TM": "TMT", "AM": "AMD", "GE": "GEL",
    "AZ": "AZN", "MD": "MDL",
    # Америка и Океания
    "US": "USD", "CA": "CAD", "MX": "MXN", "BR": "BRL", "AR": "ARS",
    "CL": "CLP", "CO": "COP", "PE": "PEN", "UY": "UYU", "BO": "BOB",
    "AU": "AUD", "NZ": "NZD", "FJ": "FJD",
    # Европа (вне еврозоны)
    "GB": "GBP", "CH": "CHF", "SE": "SEK", "NO": "NOK", "DK": "DKK",
    "IS": "ISK", "PL": "PLN", "CZ": "CZK", "HU": "HUF", "RO": "RON",
    "BG": "BGN", "RS": "RSD", "BA": "BAM", "MK": "MKD",
    # Ближний Восток и Африка
    "TR": "TRY", "IL": "ILS", "EG": "EGP", "MA": "MAD", "TN": "TND",
    "AE": "AED", "SA": "SAR", "QA": "QAR", "KW": "KWD", "BH": "BHD",
    "OM": "OMR", "JO": "JOD", "IQ": "IQD", "IR": "IRR", "LB": "LBP",
    "ZA": "ZAR", "NG": "NGN", "KE": "KES", "GH": "GHS", "TZ": "TZS",
    "DZ": "DZD", "LY": "LYD", "SD": "SDG", "ET": "ETB", "UG": "UGX",
    "AO": "AOA", "MZ": "MZN", "ZM": "ZMW", "ZW": "ZWG", "CM": "XAF",
    # Азия
    "CN": "CNY", "HK": "HKD", "MO": "MOP", "TW": "TWD", "JP": "JPY",
    "KR": "KRW", "KP": "KPW", "MN": "MNT", "VN": "VND", "TH": "THB",
    "KH": "KHR", "LA": "LAK", "MY": "MYR", "SG": "SGD", "ID": "IDR",
    "PH": "PHP", "IN": "INR", "PK": "PKR", "BD": "BDT", "LK": "LKR",
    "NP": "NPR",
}

# ---------------------------------------------------------------------------
# Названия стран (рус./англ./альтернативные) → ISO-код страны
# ---------------------------------------------------------------------------

COUNTRY_NAMES: Final[dict[str, str]] = {
    # Россия
    "россия": "RU", "российская федерация": "RU", "рф": "RU", "russia": "RU",
    "russian federation": "RU",
    # Китай
    "китай": "CN", "кнр": "CN", "китайская народная республика": "CN",
    "china": "CN", "prc": "CN",
    # Турция
    "турция": "TR", "туреччина": "TR", "turkey": "TR", "türkiye": "TR",
    # Таиланд
    "таиланд": "TH", "тайланд": "TH", "thailand": "TH",
    # ОАЭ
    "оаэ": "AE", "объединенные арабские эмираты": "AE",
    "объединённые арабские эмираты": "AE", "united arab emirates": "AE",
    "uae": "AE", "дубай": "AE",
    # Еврозона
    "италия": "IT", "italy": "IT",
    "испания": "ES", "spain": "ES",
    "франция": "FR", "france": "FR",
    "германия": "DE", "germany": "DE",
    "португалия": "PT", "portugal": "PT",
    "греция": "GR", "greece": "GR",
    "нидерланды": "NL", "голландия": "NL", "netherlands": "NL",
    "австрия": "AT", "austria": "AT",
    "бельгия": "BE", "belgium": "BE",
    "финляндия": "FI", "finland": "FI",
    "ирландия": "IE", "ireland": "IE",
    "хорватия": "HR", "croatia": "HR",
    # Прочая Европа
    "великобритания": "GB", "англия": "GB", "соединенное королевство": "GB",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB",
    "швейцария": "CH", "switzerland": "CH",
    "швеция": "SE", "sweden": "SE",
    "норвегия": "NO", "norway": "NO",
    "дания": "DK", "denmark": "DK",
    "исландия": "IS", "iceland": "IS",
    "польша": "PL", "poland": "PL",
    "чехия": "CZ", "чешская республика": "CZ", "czech republic": "CZ",
    "czechia": "CZ",
    "венгрия": "HU", "hungary": "HU",
    "румыния": "RO", "romania": "RO",
    "болгария": "BG", "bulgaria": "BG",
    "сербия": "RS", "serbia": "RS",
    "черногория": "ME", "montenegro": "ME",
    "северная македония": "MK", "македония": "MK", "macedonia": "MK",
    "украина": "UA", "ukraine": "UA",
    "беларусь": "BY", "белоруссия": "BY", "belarus": "BY",
    "казахстан": "KZ", "kazakhstan": "KZ",
    "узбекистан": "UZ", "uzbekistan": "UZ",
    "грузия": "GE", "georgia": "GE",
    "армения": "AM", "armenia": "AM",
    "азербайджан": "AZ", "azerbaijan": "AZ",
    "кыргызстан": "KG", "kyrgyzstan": "KG",
    "таджикистан": "TJ", "tajikistan": "TJ",
    # Азия
    "вьетнам": "VN", "vietnam": "VN",
    "индонезия": "ID", "indonesia": "ID",
    "малайзия": "MY", "malaysia": "MY",
    "сингапур": "SG", "singapore": "SG",
    "филиппины": "PH", "philippines": "PH",
    "япония": "JP", "japan": "JP",
    "южная корея": "KR", "корея": "KR", "south korea": "KR", "korea": "KR",
    "индия": "IN", "india": "IN",
    "израиль": "IL", "israel": "IL",
    "египет": "EG", "egypt": "EG",
    # Америка
    "сша": "US", "соединенные штаты": "US", "соединённые штаты": "US",
    "америка": "US", "united states": "US", "usa": "US",
    "канада": "CA", "canada": "CA",
    "мексика": "MX", "mexico": "MX",
    "бразилия": "BR", "brazil": "BR",
    "аргентина": "AR", "argentina": "AR",
    "австралия": "AU", "australia": "AU",
    "новая зеландия": "NZ", "new zealand": "NZ",
}

# ---------------------------------------------------------------------------
# Кеш курсов (in-memory, TTL 1 час) — чтобы не превышать лимиты API
# ---------------------------------------------------------------------------

_RATE_CACHE: TTLCache = TTLCache(maxsize=1000, ttl=3600)
_CACHE_LOCK = threading.Lock()

# Последние известные курсы (без TTL) — используются ТОЛЬКО как fallback,
# когда API недоступен, а основной кеш уже истёк.
_LAST_KNOWN: dict[tuple[str, str], float] = {}

API_BASE: Final[str] = "https://api.exchangerate.host/convert"
REQUEST_TIMEOUT: Final[int] = 10


def _cache_key(from_currency: str, to_currency: str) -> tuple[str, str]:
    """Возвращает нормализованный ключ кеша для пары валют.

    Args:
        from_currency: Исходная валюта (ISO 4217).
        to_currency: Целевая валюта (ISO 4217).

    Returns:
        Кортеж кодов валют в верхнем регистре.
    """
    return from_currency.upper(), to_currency.upper()


def _api_key() -> str:
    """Возвращает API-ключ из переменных окружения.

    Returns:
        Значение ``CURRENCY_API_KEY``.

    Raises:
        ApiError: Если ключ не задан.
    """
    key = os.getenv("CURRENCY_API_KEY", "").strip()
    if not key:
        raise ApiError("Переменная окружения CURRENCY_API_KEY не задана")
    return key


def _fetch_rate(from_currency: str, to_currency: str) -> float:
    """Запрашивает курс у API (вызывается только при промахе кеша).

    Args:
        from_currency: Исходная валюта.
        to_currency: Целевая валюта.

    Returns:
        Курс from → to.

    Raises:
        ApiError: При сетевой ошибке, лимите или ошибке ответа.
    """
    params = {
        "access_key": _api_key(),
        "from": from_currency,
        "to": to_currency,
        "amount": 1,
    }
    try:
        response = requests.get(API_BASE, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ApiError(f"Ошибка запроса к API курсов: {exc}") from exc

    if not payload.get("success", False):
        error = payload.get("error", {})
        message = error.get("info") if isinstance(error, dict) else error
        raise ApiError(f"API курсов вернул ошибку: {message or payload}")

    rate = payload.get("result")
    if not isinstance(rate, (int, float)) or rate <= 0:
        info = payload.get("info") or {}
        rate = info.get("rate") if isinstance(info, dict) else None
    if not isinstance(rate, (int, float)) or rate <= 0:
        raise ApiError("API курсов вернул некорректный курс")

    logger.info("Получен курс %s→%s: %s", from_currency, to_currency, rate)
    return float(rate)


def get_exchange_rate(from_currency: str, to_currency: str) -> float:
    """Возвращает курс ``from_currency → to_currency`` с кешированием (TTL 1 час).

    При недоступности API сначала пытается вернуть кешированный курс.

    Args:
        from_currency: Исходная валюта (ISO 4217).
        to_currency: Целевая валюта (ISO 4217).

    Returns:
        Курс from → to.

    Raises:
        ApiError: Если API недоступен и кешированного курса нет.
    """
    key = _cache_key(from_currency, to_currency)
    if key[0] == key[1]:
        return 1.0

    with _CACHE_LOCK:
        cached = _RATE_CACHE.get(key)
    if cached is not None:
        return float(cached)

    try:
        rate = _fetch_rate(key[0], key[1])
    except ApiError as exc:
        # Основной кеш истёк — пробуем последнее известное значение
        with _CACHE_LOCK:
            stale = _LAST_KNOWN.get(key)
        if stale is not None:
            logger.warning(
                "API недоступен (%s), использую последний известный курс %s",
                exc, stale,
            )
            return float(stale)
        raise

    with _CACHE_LOCK:
        _RATE_CACHE[key] = rate
        _LAST_KNOWN[key] = rate
    return rate


def convert_amount(amount: float, from_currency: str, to_currency: str) -> float:
    """Конвертирует сумму с учётом кеша курсов.

    Args:
        amount: Сумма в ``from_currency``.
        from_currency: Исходная валюта (ISO 4217).
        to_currency: Целевая валюта (ISO 4217).

    Returns:
        Сумма в ``to_currency``.

    Raises:
        ApiError: Если курс недоступен.
    """
    rate = get_exchange_rate(from_currency, to_currency)
    return amount * rate


def get_currency_by_country(country_code: str) -> str:
    """Возвращает код валюты по коду или названию страны.

    Сначала ищем ISO-код страны (3166), затем — валюту в статическом
    словаре ISO 4217 (API такого метода не предоставляет, поэтому
    используется этот fallback).

    Args:
        country_code: ISO-код страны («RU») или её название
            («Россия», «China») — регистр не важен.

    Returns:
        Код валюты ISO 4217, например ``"RUB"``.

    Raises:
        CurrencyNotFoundError: Если страна или её валюта неизвестны.
    """
    if not country_code or not country_code.strip():
        raise CurrencyNotFoundError("Страна не указана")

    query = country_code.strip()

    # 1) Попытка распознать как ISO-код страны (2 буквы)
    iso: str | None = query.upper() if len(query) == 2 and query.isalpha() else None

    # 2) Поиск по названию страны (рус./англ.), регистр не важен
    if iso not in COUNTRY_CURRENCY:
        iso = COUNTRY_NAMES.get(query.lower(), iso)

    if iso is None or iso not in COUNTRY_CURRENCY:
        raise CurrencyNotFoundError(
            f"Не удалось определить валюту для страны: {query}"
        )

    currency = COUNTRY_CURRENCY.get(iso)
    if not currency:
        raise CurrencyNotFoundError(
            f"Не удалось определить валюту для страны: {query}"
        )
    return currency
