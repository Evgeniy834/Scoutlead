import logging
import asyncio
import json
import httpx
from datetime import datetime
from urllib.parse import urlparse
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from openai import AsyncOpenAI

from configfile import BOT_TOKEN, ROUTERAI_API_KEY, ROUTERAI_BASE_URL, ROUTERAI_MODEL
from keyboardsfile import main_menu_kb, back_kb, lead_actions_kb
from databasefile import (
    get_or_create_user, save_scout_finding, 
    get_first_lead_id, get_lead_by_id, get_next_lead_id, get_prev_lead_id, delete_lead
)

logger = logging.getLogger(__name__)
router = Router()

ai_client = AsyncOpenAI(api_key=ROUTERAI_API_KEY, base_url=ROUTERAI_BASE_URL)

# Готовим две даты: для промпта (красивую) и для кода (машинную YYYY-MM-DD)
TODAY_DATETIME = datetime.now()
TODAY_STR = TODAY_DATETIME.strftime("%d %B %Y года")
TODAY_ISO = TODAY_DATETIME.strftime("%Y-%m-%d")  # Например: 2026-11-02

# Обновленный промпт: жестко задаем формат даты и требуем отсекать прошлое
SCOUT_SYSTEM_PROMPT = f"""
Ты — профессиональный B2B-разведчик. Твоя задача — найти компании в РФ, которые анонсировали офлайн-события (выставки, форумы, запуски заводов).

КРИТИЧЕСКИЕ ПРАВИЛА:
1. Ищи ТОЛЬКО на сайтах с доменом .ru, а также в Telegram (t.me) и ВКонтакте (vk.com). Игнорируй любые другие домены.
2. Ссылка должна вести на конкретную новость или пост. Ссылки на общие разделы (/news) ЗАПРЕЩЕНЫ.
3. Событие должно быть офлайн (выставка, конференция, форум, запуск завода).
4. Описание события должно быть кратким (до 10 слов).
5. СЕГОДНЯ {TODAY_STR} (формат YYYY-MM-DD: {TODAY_ISO}). 
6. ТЕБЕ НУЖНЫ ТОЛЬКО БУДУЩИЕ СОБЫТИЯ. Если событие уже прошло (дата раньше {TODAY_ISO}) — ПРОПУСКАЙ ЕГО.
7. Поле "event_date" должно быть строго в формате YYYY-MM-DD (например, 2027-03-15). Если известен только месяц и год, используй 01 (например, 2027-03-01). Если дата неизвестна, ставь null.

ФОРМАТ ОТВЕТА (строго JSON-объект с ключом "leads"):
{{
  "leads": [
    {{
      "company_name": "Название",
      "event_description": "Кратко, что делают",
      "source_url": "https://...",
      "source_type": "website / telegram / vk",
      "event_date": "2027-05-10"
    }}
  ]
}}
Если не нашел ничего подходящего — верни {{"leads": []}}.
"""

WELCOME_TEXT = "👋 Привет, <b>{name}</b>!\n\nЯ — бот для мониторинга событий клиентов.\nВыберите действие на клавиатуре ниже:"

# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================

def format_lead_card(s: dict) -> str:
    source_map = {"website": "Сайт 🌐", "telegram": "Telegram ✈️", "vk": "ВКонтакте 📱"}
    source_readable = source_map.get(s['source_type'], s['source_type'])
    return (
        f"📋 <b>Карточка лида</b> (ID: {s['id']})\n\n"
        f"<b>Ссылка:</b> {s['source_url']}\n"
        f"<b>Источник:</b> {source_readable}\n"
        f"<b>Компания:</b> {s['company_name']}\n"
        f"<b>Что делают:</b> {s['event_description']}\n"
        f"<b>Дата:</b> {s['event_date'] or 'Не указана'}\n"
    )

async def _is_url_alive(url: str) -> bool:
    if not url.startswith(('http://', 'https://')):
        return False
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    
    allowed = False
    if domain.endswith('.ru') or domain.endswith('.рф') or 't.me' in domain or 'vk.com' in domain:
        allowed = True
        
    if not allowed:
        return False

    if url.endswith(('/news', '/news/', '/PressReleases', '/PressReleases/', '/press-center', '/press-center/')):
        return False
        
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=headers) as client:
            response = await client.head(url)
            if response.status_code >= 400:
                response = await client.get(url)
            return response.status_code not in [404, 500, 502, 503, 504]
    except Exception:
        return False

def fix_truncated_json(raw_text: str) -> dict:
    try:
        data = json.loads(raw_text)
        return data if isinstance(data, dict) else {"leads": data}
    except json.JSONDecodeError:
        last_brace = raw_text.rfind('}')
        if last_brace != -1:
            try:
                data = json.loads(raw_text[:last_brace+1] + ']}')
                return data if isinstance(data, dict) else {"leads": data}
            except Exception:
                pass
        return {"leads": []}

# ==========================================
# ОСНОВНЫЕ ХЕНДЛЕРЫ
# ==========================================

@router.message(Command("start"))
async def cmd_start(message: Message):
    await get_or_create_user(message.from_user.id, message.from_user.username)
    await message.answer(WELCOME_TEXT.format(name=message.from_user.full_name), reply_markup=main_menu_kb())

@router.callback_query(F.data == "manual")
async def cb_manual(call: CallbackQuery):
    await call.message.edit_text("📖 <b>Краткий мануал</b>\n\n(Заполним позже)", reply_markup=back_kb())
    await call.answer()

@router.callback_query(F.data == "back")
async def cb_back(call: CallbackQuery):
    await call.message.edit_text(f"👋 <b>{call.from_user.full_name}</b>, вы в главном меню.", reply_markup=main_menu_kb())
    await call.answer()

@router.callback_query(F.data == "results")
async def cb_results(call: CallbackQuery):
    lead_id = await get_first_lead_id()
    if not lead_id:
        await call.message.edit_text("📋 <b>Результаты</b>\n\nБаза пуста.", reply_markup=back_kb())
        return
    lead = await get_lead_by_id(lead_id)
    if lead:
        await call.message.edit_text(format_lead_card(lead), reply_markup=lead_actions_kb(lead_id), disable_web_page_preview=True)
    await call.answer()

@router.callback_query(F.data.startswith("lead_next_"))
async def cb_lead_next(call: CallbackQuery):
    current_id = int(call.data.split("_")[2])
    next_id = await get_next_lead_id(current_id)
    if next_id:
        lead = await get_lead_by_id(next_id)
        await call.message.edit_text(format_lead_card(lead), reply_markup=lead_actions_kb(next_id), disable_web_page_preview=True)
    else:
        await call.answer("Это последняя запись.", show_alert=True)
    await call.answer()

@router.callback_query(F.data.startswith("lead_prev_"))
async def cb_lead_prev(call: CallbackQuery):
    current_id = int(call.data.split("_")[2])
    prev_id = await get_prev_lead_id(current_id)
    if prev_id:
        lead = await get_lead_by_id(prev_id)
        await call.message.edit_text(format_lead_card(lead), reply_markup=lead_actions_kb(prev_id), disable_web_page_preview=True)
    else:
        await call.answer("Это первая запись.", show_alert=True)
    await call.answer()

@router.callback_query(F.data.startswith("lead_view_"))
async def cb_lead_view(call: CallbackQuery):
    current_id = int(call.data.split("_")[2])
    await delete_lead(current_id)
    await call.answer("✅ Удалено.", show_alert=False)
    next_id = await get_next_lead_id(current_id)
    if next_id:
        lead = await get_lead_by_id(next_id)
        await call.message.edit_text(format_lead_card(lead), reply_markup=lead_actions_kb(next_id), disable_web_page_preview=True)
    else:
        prev_id = await get_prev_lead_id(current_id)
        if prev_id:
            lead = await get_lead_by_id(prev_id)
            await call.message.edit_text(format_lead_card(lead), reply_markup=lead_actions_kb(prev_id), disable_web_page_preview=True)
        else:
            await call.message.edit_text("📋 <b>Результаты</b>\n\nВсе лиды просмотрены.", reply_markup=back_kb())

# ==========================================
# ЗАПУСК СКАУТЕРА (С ПРОВЕРКОЙ ДАТ)
# ==========================================

async def run_scout_agent(chat_id: int, bot: Bot):
    logger.info("[SCOUT] Запуск поиска (с проверкой дат)...")
    try:
        response = await ai_client.chat.completions.create(
            model=ROUTERAI_MODEL, 
            messages=[
                {"role": "system", "content": SCOUT_SYSTEM_PROMPT},
                {"role": "user", "content": "Найди не менее 5 свежих анонсов от российских компаний. События должны быть в будущем (после ноября 2026 года)."}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=8192,
            extra_body={
                "plugins": [
                    {
                        "id": "web",
                        "include_domains": ["*.ru", "t.me", "vk.com"]
                    }
                ]
            }
        )
        
        usage = response.usage
        logger.info(f"[SCOUT] Ответ получен. Токенов: {usage.total_tokens}")
        
        raw_content = response.choices[0].message.content
        logger.info(f"[SCOUT] Сырой ответ от ИИ: {raw_content[:300]}...")
        
        clean_json = raw_content.strip().replace("```json", "").replace("```", "")
        parsed_data = fix_truncated_json(clean_json)
        findings = parsed_data.get("leads", [])
        
        if not findings:
            await bot.send_message(chat_id, "⚠️ ИИ не нашел подходящих событий.")
            return
            
        total_new_found = 0
        for item in findings:
            company = item.get("company_name", "Неизвестно")
            url = item.get("source_url", "")
            event_date = item.get("event_date")

            # 1. ПРОГРАММНАЯ ПРОВЕРКА ДАТЫ (Если дата в прошлом — отсекаем)
            if event_date and isinstance(event_date, str):
                # Проверяем формат YYYY-MM-DD
                if len(event_date) >= 10:
                    clean_date = event_date[:10]
                    if clean_date < TODAY_ISO: # Сравнение строк работает идеально для ISO-дат
                        logger.warning(f"[SCOUT] Отсеян прошедший ивент ({clean_date} < {TODAY_ISO}): {company}")
                        continue

            # 2. Проверка домена и живучести ссылки
            if not await _is_url_alive(url):
                logger.warning(f"[SCOUT] Ссылка отсеяна: {company} ({url})")
                continue

            # 3. Сохранение в БД
            saved = await save_scout_finding(
                company_name=company,
                event_description=item.get("event_description"),
                source_url=url,
                source_type=item.get("source_type", "website"),
                event_date=event_date
            )
            if saved:
                total_new_found += 1
                logger.info(f"[SCOUT] Сохранен лид: {company} (Дата: {event_date})")
                
        logger.info(f"[SCOUT] Итог. Новых: {total_new_found}")
        
        msg = f"✅ <b>Поиск завершен!</b>\n"
        if total_new_found > 0:
            msg += f"Найдено и сохранено новых лидов: <b>{total_new_found}</b>."
        else:
            msg += "Новых лидов не найдено (все ссылки или даты не прошли фильтр)."
            
        await bot.send_message(chat_id, msg)
            
    except Exception as e:
        logger.error(f"[SCOUT] Критическая ошибка: {e}", exc_info=True)
        await bot.send_message(chat_id, "⚠️ Ошибка при запросе к нейросети.")

@router.callback_query(F.data == "start_search")
async def cb_start_search(call: CallbackQuery):
    await call.answer("Поиск запущен! Ожидайте...", show_alert=True)
    await call.message.edit_text("🚀 <b>Поиск запущен!</b>\n\nИщем только на .ru, t.me, vk.com и проверяем даты...", reply_markup=back_kb())
    asyncio.create_task(run_scout_agent(call.message.chat.id, call.bot))

@router.message()
async def catch_all_messages(message: Message):
    await message.answer("Я пока не понимаю эту команду. Воспользуйтесь меню /start")