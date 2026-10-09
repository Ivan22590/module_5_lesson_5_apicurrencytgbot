🎯 Роль и контекст
Ты — Senior Python-разработчик с глубоким опытом создания Telegram-ботов. Твоя задача — написать production-ready Telegram-бота «Мини-кошелёк путешественника», который помогает пользователям отслеживать расходы во время поездок в двух валютах одновременно.
🛠 Технический стек (строго)
Язык: Python 3.11+ с обязательным использованием type hints (PEP 484)
Библиотека бота: pyTelegramBotAPI (telebot)
API курсов: https://api.exchangerate.host (ТОЛЬКО этот сервис, без альтернатив и mock-данных)
База данных: SQLite через sqlite3 (без ORM)
Конфигурация: .env через python-dotenv
Кеширование: in-memory кеш курсов (например, cachetools или dict + TTL 1 час), чтобы не превышать лимиты API
Логирование: стандартный logging в файл bot.log (уровень INFO + ошибки отдельно)
Форматирование сообщений: HTML-разметка (жирный, код, моноширинный)

/
├── .env                      # TELEGRAM_BOT_TOKEN, CURRENCY_API_KEY
├── .gitignore
├── requirements.txt
├── README.md
├── main.py                   # точка входа, регистрация хендлеров
├── config.py                 # загрузка .env, константы
├── database.py               # работа с SQLite (init, запросы)
├── currency_api.py           # модуль для работы с api.exchangerate.host
├── handlers/
│   ├── __init__.py
│   ├── start.py              # /start, главное меню
│   ├── trip.py               # создание/переключение путешествий
│   ├── expense.py            # учёт расходов
│   └── callbacks.py          # обработка inline-кнопок
├── keyboards.py              # все Reply и Inline-клавиатуры
├── states.py                 # FSM-состояния пользователя (через user_data)
├── schemas.sql               # схема БД
└── utils.py                  # форматирование валют, дат, валидация

🗄 Схема БД (schemas.sql)

CREATE TABLE users (
    telegram_id INTEGER PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE trips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,           -- например, "Китай 2026"
    from_country TEXT NOT NULL,
    to_country TEXT NOT NULL,
    from_currency TEXT NOT NULL,   -- RUB
    to_currency TEXT NOT NULL,     -- CNY
    rate REAL NOT NULL,            -- курс from → to
    rate_manual BOOLEAN DEFAULT FALSE, -- ручной или API
    initial_amount REAL NOT NULL,  -- стартовая сумма в from_currency
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (user_id) REFERENCES users(telegram_id)
);

CREATE TABLE expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL,
    amount REAL NOT NULL,          -- сумма в валюте страны назначения
    amount_home REAL NOT NULL,     -- пересчёт в домашнюю валюту
    rate_used REAL NOT NULL,
    category TEXT DEFAULT 'Прочее',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (trip_id) REFERENCES trips(id)
);

🔌 Модуль currency_api.py
Функции, которые должен предоставлять модуль:
get_currency_by_country(country_code: str) -> str | None — возвращает код валюты по ISO-коду страны (если API такого метода не имеет — использовать статический словарь ISO 4217 как fallback).
get_exchange_rate(from_currency: str, to_currency: str) -> float | None — запрос к http://api.exchangerate.host/convert с параметром access_key={CURRENCY_API_KEY}. Возвращает курс с кешированием (TTL 1 час).
convert_amount(amount: float, from_currency: str, to_currency: str) -> float | None — конвертация с учётом кеша.
Все функции должны выбрасывать кастомные исключения ApiError, CurrencyNotFoundError, которые перехватываются в хендлерах.
🎨 Главное меню и inline-навигация

После /start пользователь видит Reply-клавиатуру с 5 кнопками (одна под другой):
🆕 Создать путешествие
📂 Мои путешествия
💰 Баланс
📊 История расходов
⚙️ Изменить курс

Команды-дубликаты: /newtrip, /switch, /balance, /history, /setrate.

🔄 Бизнес-логика (обязательные сценарии)
1. Создание путешествия (FSM)
Пользователь вводит страну отправления (текст или выбор из популярных).
Бот определяет её валюту через currency_api.py.
Пользователь вводит страну назначения.
Бот определяет её валюту.
Бот получает актуальный курс и показывает: «Курс: 1 EUR = 104 RUB. Подтвердить? [Да/Нет]».
При «Нет» — просит ввести курс вручную и помечает rate_manual=TRUE.
Пользователь вводит стартовую сумму в домашней валюте.
Бот конвертирует её, создаёт Trip, показывает итог: «✅ Путешествие «Италия» создано. Баланс: 200 000 ₽ = ≈1 923 €».
2. Учёт расхода
Активное путешествие выбирается автоматически (последнее активное) или через кнопку «Мои путешествия».
Любое сообщение-число от пользователя = трата в валюте страны назначения.
Бот конвертирует в домашнюю валюту и показывает подтверждение:
100 CNY = 1 280 RUB
[✅ Учесть расход] [❌ Отмена]
По нажатию «Да» — запись в expenses, списание с баланса, вывод обновлённого остатка:
Остаток: 2 400 CNY = 30 720 RUB
3. Переключение путешествий
Кнопка «📂 Мои путешествия» → inline-кнопки со списком всех путешествий пользователя. Клик активирует выбранное и делает его is_active=TRUE, остальные — FALSE.
4. История расходов
Пагинация по 5 записей с кнопками «◀️ Назад / Вперёд ▶️». Каждая запись:
🍽 500 CNY (≈ 6 400 ₽)
📅 09.10.2026 14:32

В конце — итоговая сумма расходов в обеих валютах.
⚠️ Обработка ошибок (обязательно)
Не число вместо суммы → «Пожалуйста, отправьте число».
Неизвестная страна/валюта → «Не удалось определить валюту для этой страны. Проверьте название».
API недоступен / лимит → «Сервис курсов временно недоступен, попробуйте позже». Использовать кешированный курс, если есть.
Нет активного путешествия при учёте расхода → предложить создать/выбрать.
Любое необработанное исключение в try/except с логированием и дружелюбным сообщением пользователю.
✅ Нефункциональные требования
Каждый пользователь изолирован (все запросы фильтруются по telegram_id).
Все SQL-запросы — через параметризованные запросы (?-плейсхолдеры), защита от SQL-инъекций.
Код покрыт docstrings (Google style).
Переменные окружения валидируются при старте (падать с понятной ошибкой, если их нет).
📦 Дополнительно
Установить зависимости в виртуальное окружение (python -m venv venv).
requirements.txt должен содержать зафиксированные версии.
В README.md — инструкция по запуску, переменные окружения, примеры команд, скриншоты меню.
.gitignore должен исключать .env, venv/, *.db, __pycache__/, .venv/, bot.log.
📸 Примеры сценариев (коротко)
Сценарий 1: Россия → Италия. Старт: 200 000 ₽ ≈ 1 923 €. Трата: 50 € → бот пишет «50 € = 5 200 ₽», пользователь подтверждает, остаток: 1 873 € / 194 800 ₽.
Сценарий 2: Россия → Китай. Стартовая сумма 1 000 ₽ конвертируется в CNY по актуальному курсу.