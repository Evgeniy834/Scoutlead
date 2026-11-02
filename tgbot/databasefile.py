import aiosqlite
import os
import logging
import json
from configfile import DB_PATH

logger = logging.getLogger(__name__)

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    role TEXT DEFAULT 'manager',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Новая таблица для результатов работы Скаутера (1-я модель)
CREATE TABLE IF NOT EXISTS scout_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT,
    event_description TEXT,
    source_url TEXT UNIQUE, -- Ссылка уникальна, чтобы не дублировать
    source_type TEXT,
    event_date TEXT,
    status TEXT DEFAULT 'new', -- new | processed (когда 2-я модель ее обработает)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS failed_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage TEXT,
    payload TEXT,
    error TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

async def init_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.executescript(CREATE_TABLES_SQL)
            await db.commit()
        logger.info("База данных успешно инициализирована. Путь: %s", DB_PATH)
    except Exception as e:
        logger.critical("Критическая ошибка при инициализации БД: %s", e, exc_info=True)
        raise e

async def get_or_create_user(user_id: int, username: str | None) -> int:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT id FROM users WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
            if row:
                return row[0]
            async with db.execute(
                "INSERT INTO users (user_id, username) VALUES (?, ?)", (user_id, username)
            ) as cur:
                await db.commit()
                return cur.lastrowid
    except Exception as e:
        logger.error("Ошибка БД в get_or_create_user: %s", e, exc_info=True)
        return 0

async def save_scout_finding(company_name: str, event_description: str, source_url: str, source_type: str, event_date: str | None) -> bool:
    """Сохраняет найденную Скаутером ссылку в БД. Возвращает True, если запись добавлена."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # INSERT OR IGNORE не даст упасть, если ссылка уже есть
            async with db.execute(
                "INSERT OR IGNORE INTO scout_findings (company_name, event_description, source_url, source_type, event_date) VALUES (?, ?, ?, ?, ?)",
                (company_name, event_description, source_url, source_type, event_date),
            ) as cur:
                await db.commit()
                if cur.rowcount > 0:
                    logger.info(f"В БД сохранен новый лид от Скаутера: {company_name} ({source_url})")
                    return True
                return False
    except Exception as e:
        logger.error("Ошибка БД в save_scout_finding: %s", e, exc_info=True)
        return False

async def get_daily_stats() -> dict:
    """Статистика для меню истории."""
    try:
        stats = {"sites": 0, "telegram": 0, "vk": 0, "total": 0}
        async with aiosqlite.connect(DB_PATH) as db:
            # Считаем всё, что нашел Скаутер за 24 часа
            async with db.execute("SELECT source_type, COUNT(*) FROM scout_findings WHERE created_at >= datetime('now', '-1 day') GROUP BY source_type") as cur:
                rows = await cur.fetchall()
                for row in rows:
                    if row[0] == 'website': stats['sites'] = row[1]
                    elif row[0] == 'telegram': stats['telegram'] = row[1]
                    elif row[0] == 'vk': stats['vk'] = row[1]
                    stats['total'] += row[1]
        return stats
    except Exception as e:
        logger.error("Ошибка БД в get_daily_stats: %s", e, exc_info=True)
        return {"sites": 0, "telegram": 0, "vk": 0, "total": 0}