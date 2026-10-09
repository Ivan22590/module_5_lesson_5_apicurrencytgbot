-- Схема базы данных SQLite для бота «Мини-кошелёк путешественника».

CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trips (
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

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL,
    amount REAL NOT NULL,          -- сумма в валюте страны назначения
    amount_home REAL NOT NULL,     -- пересчёт в домашнюю валюту
    rate_used REAL NOT NULL,
    category TEXT DEFAULT 'Прочее',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (trip_id) REFERENCES trips(id)
);

-- Индексы для ускорения выборок
CREATE INDEX IF NOT EXISTS idx_trips_user_id ON trips(user_id);
CREATE INDEX IF NOT EXISTS idx_expenses_trip_id ON expenses(trip_id);
