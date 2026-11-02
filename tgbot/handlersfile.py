import logging
import asyncio
import json
import httpx
import time
from datetime import datetime
from urllib.parse import urlparse
from bs4 import BeautifulSoup 
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from openai import AsyncOpenAI

from configfile import BOT_TOKEN, ROUTERAI_API_KEY, ROUTERAI_BASE_URL, ROUTERAI_MODEL
from keyboardsfile import main_menu_kb, back_kb, lead_actions_kb
from databasefile import (
    get_or_create_user, save_scout_finding, 
    get_first_lead_id, get_lead_by_id, get_next_lead_id, get_prev_lead_id, delete_lead,
    get_new_leads, update_lead_status 
)

logger = logging.getLogger(__name__)
router = Router()

ai_client = AsyncOpenAI(api_key=ROUTERAI_API_KEY, base_url=ROUTERAI_BASE_URL)

TODAY_DATETIME = datetime.now()
TODAY_STR = TODAY_DATETIME.strftime("%d %B %Y года")
TODAY_ISO = TODAY_DATETIME.strftime("%Y-%m-%d")

SCOUT_SYSTEM_PROMPT = f"""
Ты — профессиональный B2B-разведчик. Твоя задача — найти компании в РФ, которые анонсировали офлайн-события (выставки, форумы, запуски заводов).

КРИТИЧЕСКИЕ ПРАВИЛА:
1. Ищи ТОЛЬКО на сайтах с доменом .ru, а также в Telegram (t.me) и ВКонтакте (vk.com).
2. Ссылка должна вести на конкретную новость или пост. Ссылки на общие разделы (/news) ЗАПРЕЩЕНЫ.
3. Событие должно быть офлайн (выставка, конференция, форум, запуск завода).
4. Описание события должно быть кратким (до 10 слов).
5. СЕГОДНЯ {TODAY_STR} ({TODAY_ISO}). 
6. ТЕБЕ НУЖНЫ ТОЛЬКО БУДУЩИЕ СОБЫТИЯ. Если событие уже прошло — ПРОПУСКАЙ.
7. Поле "event_date" строго в формате YYYY-MM-DD (например, 2027-03-15). Если известен только месяц и год, используй 01.

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

# ПРОМПТ ДЛЯ АНАЛИТИКА 
ANALYST_SYSTEM_PROMPT = f"""
Ты — строгий аналитик-верификатор базы данных. Твоя задача — прочитать предоставленный текст страницы и решить, является ли он качественным B2B-лидом, или это мусор.

КРИТЕРИИ ДЛЯ ПРИНЯТИЯ РЕШЕНИЯ "KEEP" (оставить):
1. В тексте явно упоминается анонс офлайн-события (выставка, конференция, форум, открытие завода).
2. Это не просто новость о выходе отчета или биржевых облигациях.
3. Дата события (если она есть в тексте) находится в будущем (сегодня {TODAY_ISO}).
4. Компания является коммерческой организацией РФ.

КРИТЕРИИ ДЛЯ "DELETE" (удалить):
1. Текст не содержит анонса события (например, это статья о погоде, общие рассуждения, финансовые новости).
2. Событие уже прошло.
3. Это новостная перепечатка со стороннего СМИ, а не официальный анонс компании.

ВЕРНИ ОТВЕТ СТРОГО В ФОРМАТЕ JSON:
{{
  "verdict": "KEEP" или "DELETE",
  "reason": "Краткая причина (до 10 слов)"
}}
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
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        if not (domain.endswith('.ru') or domain.endswith('.рф') or 't.me' in domain or 'vk.com' in domain):
            return False

        if url.endswith(('/news', '/news/', '/PressReleases', '/PressReleases/', '/press-center', '/press-center/')):
            return False
            
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True, headers=headers, verify=False) as client:
            response = await client.head(url)
            if response.status_code >= 400:
                response = await client.get(url)
            return response.status_code not in [404, 500, 502, 503, 504]
    except asyncio.TimeoutError:
        print(f"\n[!!!] ТАЙМАУТ ПРОВЕРКИ ССЫЛКИ: {url}\n")
        return False
    except Exception as e:
        print(f"\n[!!!] ОШИБКА ПРОВЕРКИ ССЫЛКИ {url}: {e}\n")
        return False

def fix_truncated_json(raw_text: str) -> dict:
    if not raw_text or not raw_text.strip():
        return {"leads": []}
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

async def _safe_send(bot: Bot, chat_id: int, text: str) -> bool:
    try:
        await asyncio.wait_for(bot.send_message(chat_id, text), timeout=10.0)
        return True
    except asyncio.TimeoutError:
        print(f"\n[!!!] ТАЙМАУТ ОТПРАВКИ СООБЩЕНИЯ (10 сек)\n")
        return False
    except Exception as e:
        print(f"\n[!!!] ОШИБКА ОТПРАВКИ: {e}\n")
        return False

# <--- НОВАЯ ФУНКЦИЯ ПАРСИНГА СТРАНИЦЫ --->
async def _fetch_page_text(url: str) -> str:
    """Скачивает страницу и вытаскивает чистый текст для Аналитика."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=headers, verify=False) as client:
            response = await client.get(url)
            if response.status_code >= 400:
                return ""
            
            soup = BeautifulSoup(response.text, 'html.parser')
            for script in soup(["script", "style"]):
                script.extract()
            text = soup.get_text(separator=' ')
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            clean_text = ' '.join(chunk for chunk in chunks if chunk)
            return clean_text[:5000] 
    except Exception as e:
        print(f"\n[!!!] ОШИБКА СКАЧИВАНИЯ СТРАНИЦЫ {url}: {e}\n")
        return ""

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
# ЛОГИКА ВТОРОГО АГЕНТА (АНАЛИТИК)
# ==========================================
async def run_analyst_agent(chat_id: int, bot: Bot):
    logger.info("[ANALYST] === ЗАПУСК ВТОРОГО АГЕНТА (АНАЛИТИК) ===")
    await _safe_send(bot, chat_id, "🧹 <b>Аналитик приступил к работе!</b>\nПроверяем найденные ссылки и чистим мусор...")
    
    leads = await get_new_leads()
    if not leads:
        logger.info("[ANALYST] Нет новых лидов для проверки.")
        await _safe_send(bot, chat_id, "🤷‍♂️ Аналитику нечего проверять (база пуста).")
        return

    kept_count = 0
    deleted_count = 0

    for lead in leads:
        lead_id = lead['id']
        url = lead['source_url']
        company = lead['company_name']
        
        logger.info(f"[ANALYST] Проверка лида ID {lead_id} ({company})...")
        
        # 1. Скачиваем текст страницы
        page_text = await _fetch_page_text(url)
        if not page_text:
            logger.warning(f"[ANALYST] Не удалось прочитать страницу {url}. Удаляем лид.")
            await delete_lead(lead_id)
            deleted_count += 1
            continue

       
        try:
            response = await asyncio.wait_for(
                ai_client.chat.completions.create(
                    model=ROUTERAI_MODEL, 
                    messages=[
                        {"role": "system", "content": ANALYST_SYSTEM_PROMPT},
                        {"role": "user", "content": f"Текст страницы:\n{page_text}"}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.0,
                    max_tokens=500
                ),
                timeout=60.0
            )
            
            raw_json = response.choices[0].message.content
            result = json.loads(raw_json)
            
            verdict = result.get("verdict", "DELETE")
            reason = result.get("reason", "Без причины")
            
            if verdict == "KEEP":
                await update_lead_status(lead_id, "approved")
                kept_count += 1
                logger.info(f"[ANALYST] Лид ID {lead_id} ОДОБРЕН. Причина: {reason}")
            else:
                await delete_lead(lead_id)
                deleted_count += 1
                logger.info(f"[ANALYST] Лид ID {lead_id} УДАЛЕН. Причина: {reason}")
                
        except Exception as e:
            logger.error(f"[ANALYST] Ошибка при анализе лида {lead_id}: {e}")
            # Если нейросеть сломалась, оставляем лид в базе, но помечаем как ошибочный
            await update_lead_status(lead_id, "error")
            continue

    logger.info(f"[ANALYST] === РАБОТА ЗАВЕРШЕНА. Одобрено: {kept_count}, Удалено: {deleted_count} ===")
    await _safe_send(bot, chat_id, f"✅ <b>Аналитик закончил работу!</b>\nОдобрено: {kept_count}\nУдалено мусора: {deleted_count}")


# ==========================================
# ЗАПУСК СКАУТЕРА И ТРИГГЕР ДЛЯ АНАЛИТИКА
# ==========================================

async def run_scout_agent(chat_id: int, bot: Bot):
    logger.info("[SCOUT] Запуск поиска...")
    last_save_time = time.time() 
    
    try:
        async def _search_and_save():
            nonlocal last_save_time 
            
            try:
                try:
                    response = await asyncio.wait_for(
                        ai_client.chat.completions.create(
                            model=ROUTERAI_MODEL, 
                            messages=[
                                {"role": "system", "content": SCOUT_SYSTEM_PROMPT},
                                {"role": "user", "content": "Найди не менее 5 свежих анонсов от российских компаний. События должны быть в будущем."}
                            ],
                            response_format={"type": "json_object"},
                            temperature=0.0,
                            max_tokens=16000,
                            extra_body={"plugins": [{"id": "web", "include_domains": ["*.ru", "t.me", "vk.com"]}]}
                        ),
                        timeout=120.0
                    )
                except asyncio.TimeoutError:
                    print("\n[!!!] ТАЙМАУТ ОТВЕТА ИИ (120 сек)\n")
                    await _safe_send(bot, chat_id, "⚠️ ИИ не ответил за 2 минуты. Попробуйте позже.")
                    return
                
                logger.info(f"[SCOUT] Ответ получен. Токенов: {response.usage.total_tokens}")
                
                raw_content = response.choices[0].message.content
                if not raw_content:
                    raw_content = getattr(response.choices[0].message, 'reasoning_content', None)
                    
                if not raw_content:
                    logger.warning("[SCOUT] Модель вернула пустой ответ.")
                    await _safe_send(bot, chat_id, "⚠️ Модель не смогла сгенерировать ответ.")
                    return
                    
                logger.info(f"[SCOUT] Сырой ответ (первые 200 символов): {raw_content[:200]}...")
                
                clean_json = raw_content.strip().replace("```json", "").replace("```", "")
                parsed_data = fix_truncated_json(clean_json)
                findings = parsed_data.get("leads", [])
                
                if not findings:
                    await _safe_send(bot, chat_id, "⚠️ ИИ не нашел подходящих событий (leads пуст).")
                    return
                
                total_new_found = 0
                for item in findings:
                    try:
                        company = item.get("company_name", "Неизвестно")
                        url = item.get("source_url", "")
                        event_date = item.get("event_date")

                        if event_date and isinstance(event_date, str) and len(event_date) >= 10:
                            if event_date[:10] < TODAY_ISO:
                                logger.warning(f"[SCOUT] Отсеян прошедший ивент: {company}")
                                continue

                        if not await _is_url_alive(url):
                            logger.warning(f"[SCOUT] Ссылка отсеяна: {company} ({url})")
                            continue

                        saved = await save_scout_finding(
                            company_name=company,
                            event_description=item.get("event_description"),
                            source_url=url,
                            source_type=item.get("source_type", "website"),
                            event_date=event_date
                        )
                        if saved:
                            total_new_found += 1
                            last_save_time = time.time()
                    except Exception as item_error:
                        print(f"\n[!!!] ОШИБКА ПРИ ОБРАБОТКЕ ЛИДА {item}: {item_error}\n")
                        continue
                        
                logger.info(f"[SCOUT] Итог. Новых: {total_new_found}")
                
                msg_text = f"✅ <b>Поиск Скаутера завершен!</b>\nСохранено новых лидов: <b>{total_new_found}</b>."
                await _safe_send(bot, chat_id, msg_text)
                
            except Exception as e:
                print(f"\n[!!!] КРИТИЧЕСКАЯ ОШИБКА ВНУТРИ _search_and_save: {e}\n")
                logger.error(f"[SCOUT] Ошибка внутри _search_and_save: {e}", exc_info=True)
                await _safe_send(bot, chat_id, f"⚠️ Ошибка: {str(e)[:100]}")
            
        # Внешний таймаут на всю операцию (3 минуты)
        await asyncio.wait_for(_search_and_save(), timeout=180.0)
        
    except asyncio.TimeoutError:
        logger.error("[SCOUT] Общий таймаут поиска (3 минуты)!")
        await _safe_send(bot, chat_id, "⚠️ Поиск занял слишком много времени (3 минуты).")
    except Exception as e:
        print(f"\n[!!!] КРИТИЧЕСКАЯ ОШИБКА: {e}\n")
        logger.error(f"[SCOUT] Критическая ошибка: {e}", exc_info=True)
        await _safe_send(bot, chat_id, "⚠️ Критическая ошибка при поиске.")
    finally:

        logger.info("[SCOUT] Ожидание 10 секунд тишины перед запуском Аналитика...")
        await asyncio.sleep(10)
        
        time_since_last_save = time.time() - last_save_time
        if time_since_last_save >= 10:
            logger.info(f"[SCOUT] Логируем таймаут ({time_since_last_save:.1f} сек без новых данных). Передаем управление Аналитику.")
            await run_analyst_agent(chat_id, bot)
        else:
            logger.info(f"[SCOUT] С момента последнего сохранения прошло {time_since_last_save:.1f} сек (меньше 10).")


@router.callback_query(F.data == "start_search")
async def cb_start_search(call: CallbackQuery):
    await call.answer("Поиск запущен! Ожидайте...", show_alert=True)
    await call.message.edit_text("🚀 <b>Поиск запущен!</b>\n\nСкаутер ищет лиды, затем Аналитик их проверяет...", reply_markup=back_kb())
    asyncio.create_task(run_scout_agent(call.message.chat.id, call.bot))

@router.message()
async def catch_all_messages(message: Message):
    await message.answer("Я пока не понимаю эту команду. Воспользуйтесь меню /start")