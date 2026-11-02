import aiosqlite
import os
import logging
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

CREATE TABLE IF NOT EXISTS scout_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT,
    event_description TEXT,
    source_url TEXT UNIQUE,
    source_type TEXT,
    event_date TEXT,
    status TEXT DEFAULT 'new',
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
    except Exception as e:
        logger.critical("Критическая ошибка при инициализации БД: %s", e, exc_info=True)

async def get_or_create_user(user_id: int, username: str | None) -> int:
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

async def save_scout_finding(company_name: str, event_description: str, source_url: str, source_type: str, event_date: str | None) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "INSERT OR IGNORE INTO scout_findings (company_name, event_description, source_url, source_type, event_date) VALUES (?, ?, ?, ?, ?)",
                (company_name, event_description, source_url, source_type, event_date),
            ) as cur:
                await db.commit()
                return cur.rowcount > 0
    except Exception as e:
        logger.error("Ошибка БД в save_scout_finding: %s", e, exc_info=True)
        return False

# --- НОВАЯ ЛОГИКА: САМЫЕ СВЕЖИЕ ЛИДЫ ВСЕГДА ПЕРВЫМИ ---

async def get_first_lead_id() -> int | None:
    """Берет самый последний (свежий) добавленный лид."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM scout_findings ORDER BY id DESC LIMIT 1") as cur:
            row = await cur.fetchone()
            return row[0] if row else None

async def get_lead_by_id(lead_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM scout_findings WHERE id = ?", (lead_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def get_next_lead_id(current_id: int) -> int | None:
    """Кнопка 'Дальше' (листаем вниз, к старым)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM scout_findings WHERE id < ? ORDER BY id DESC LIMIT 1", (current_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

async def get_prev_lead_id(current_id: int) -> int | None:
    """Кнопка 'Назад' (листаем вверх, к новым)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM scout_findings WHERE id > ? ORDER BY id ASC LIMIT 1", (current_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

async def delete_lead(lead_id: int) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("DELETE FROM scout_findings WHERE id = ?", (lead_id,)) as cur:
                await db.commit()
                return cur.rowcount > 0
    except Exception as e:
        logger.error("Ошибка БД в delete_lead: %s", e, exc_info=True)
        return False

# ============================================================
# НОВЫЕ ФУНКЦИИ ДЛЯ ВТОРОГО АГЕНТА (АНАЛИТИК)
# ============================================================

async def get_new_leads() -> list[dict]:
    """Достает все лиды со статусом 'new' для Аналитика."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM scout_findings WHERE status = 'new'") as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

async def update_lead_status(lead_id: int, status: str) -> bool:
    """Меняет статус лида (например, на 'approved')."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE scout_findings SET status = ? WHERE id = ?", (status, lead_id))
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Ошибка БД в update_lead_status: {e}")
        return False