import logging
import asyncio
import json
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from openai import AsyncOpenAI

from configfile import ROUTERAI_API_KEY, ROUTERAI_BASE_URL, ROUTERAI_MODEL
from keyboardsfile import main_menu_kb, back_kb, history_menu_kb, back_to_history_kb
from databasefile import get_or_create_user, get_daily_stats, save_scout_finding

logger = logging.getLogger(__name__)
router = Router()

# Инициализируем клиент RouterAI (используем библиотеку OpenAI)
ai_client = AsyncOpenAI(
    api_key=ROUTERAI_API_KEY,
    base_url=ROUTERAI_BASE_URL
)

# Системный промпт (6 шагов)
SCOUT_SYSTEM_PROMPT = """
1. РОЛЬ
Ты — профессиональный B2B-разведчик и эксперт по OSINT. Твоя задача — находить компании в Российской Федерации, которые недавно публично анонсировали крупные события (выставки, конференции, запуски новых продуктов, открытие заводов). Нам нужны их официальные источники, чтобы предложить услуги по созданию видеоконтента для этих событий.

2. ПЕРВЫЙ ШАГ (Планирование)
Не жди, пока тебе дадут название компании. Ты должен сам придумать 3–5 поисковых запросов, чтобы найти нужные анонсы. Используй формулировки, которые компании используют в своих пресс-релизах (например: «планируем представить стенд на выставке», «примем участие в конференции», «анонсируем запуск производства», «открытие нового завода 2027»). Обязательно добавляй к запросам уточнения (РФ, Россия, 2027 год).

3. ЧТО СДЕЛАТЬ С ЗАПРОСАМИ (Поиск)
Выполни поиск по этим запросам. Твоя цель — найти первоисточники: официальные сайты компаний, их Telegram-каналы или страницы ВК. Отсекай новостные агрегаторы, каталоги и статьи, написанные журналистами. Ищи именно то, что компания написала сама о себе.

4. ПРИМЕРНЫЙ РЕЗУЛЬТАТ
Ты должен найти пост или страницу, где компания пишет о своих планах. Пример: «Компания "ТехноНиколь" на своей странице ВК сообщила, что представит новые кровельные решения на выставке Expo-2027 в марте».

5. ЧТО СДЕЛАТЬ С РЕЗУЛЬТАТОМ (Формат и сохранение)
Верни результат строго в формате JSON-массива. Каждый объект — это найденное событие:
[
  {
    "company_name": "Название компании",
    "event_description": "Что именно они планируют (кратко)",
    "source_url": "Прямая ссылка на этот пост/страницу",
    "source_type": "telegram / website / vk",
    "event_date": "Дата события (если указана, иначе null)"
  }
]
Жесткое ограничение: работаем только с компаниями, которые находятся и ведут деятельность в РФ. Если не можешь подтвердить, что компания российская — пропускай.

6. ЗАЧЕМ НАМ ЭТО НУЖНО
Эти ссылки попадут в базу данных. На их основе менеджеры будут писать проактивные письма компаниям, ссылаясь на их же события, чтобы продать услуги видеопродакшна. Твоя точность (без мусора и фейков) критически важна для эффективности всей кампании.
"""

WELCOME_TEXT = (
    "👋 Привет, <b>{name}</b>!\n\n"
    "Я — бот для мониторинга событий клиентов.\n"
    "Выберите действие на клавиатуре ниже:"
)

@router.message(Command("start"))
async def cmd_start(message: Message):
    logger.info("Пользователь %s (@%s) вызвал команду /start", message.from_user.id, message.from_user.username)
    try:
        await get_or_create_user(message.from_user.id, message.from_user.username)
        await message.answer(
            WELCOME_TEXT.format(name=message.from_user.full_name),
            reply_markup=main_menu_kb(),
        )
    except Exception as e:
        logger.error("Ошибка в обработчике /start (user_id=%s): %s", message.from_user.id, e, exc_info=True)
        await message.answer("⚠️ Произошла ошибка при запуске. Попробуйте позже.")

@router.callback_query(F.data == "manual")
async def cb_manual(call: CallbackQuery):
    logger.info("Пользователь %s открыл мануал", call.from_user.id)
    text = (
        "📖 <b>Краткий мануал</b>\n\n"
        "Здесь будет подробная инструкция по работе с ботом.\n"
        "(Заполним на финальном этапе)"
    )
    try:
        await call.message.edit_text(text, reply_markup=back_kb())
    except Exception as e:
        logger.error("Ошибка в cb_manual: %s", e, exc_info=True)
    finally:
        await call.answer()

@router.callback_query(F.data == "history")
async def cb_history(call: CallbackQuery):
    logger.info("Пользователь %s открыл меню истории", call.from_user.id)
    text = (
        "📊 <b>История поиска</b>\n\n"
        "Выберите, где именно вы хотите посмотреть найденные события за последние 24 часа:"
    )
    try:
        await call.message.edit_text(text, reply_markup=history_menu_kb())
    except Exception as e:
        logger.error("Ошибка в cb_history: %s", e, exc_info=True)
        await call.answer("Ошибка", show_alert=True)
    finally:
        await call.answer()

# ==========================================
# ОБРАБОТЧИКИ КОНКРЕТНЫХ ИСТОЧНИКОВ (Сохранены без изменений)
# ==========================================

@router.callback_query(F.data == "history_sites")
async def cb_history_sites(call: CallbackQuery):
    logger.info("Пользователь %s запросил историю сайтов", call.from_user.id)
    try:
        s = {
            "ссылка": "https://example.com/news/123",
            "что_делают": "Анонс участия в выставке Expo-2027",
            "компания": "ТехноНиколь",
            "дата": "Март 2027"
        }
        text = (
            "📊 <b>История за сутки</b>\n\n"
            f"Ссылка на сайта: <b>{s['ссылка']}</b>\n"
            f"Что делают: <b>{s['что_делают']}</b>\n"
            f"Компания: <b>{s['компания']}</b>\n"
            f"Дата: <b>{s['дата']}</b>\n"
        )
        await call.message.edit_text(text, reply_markup=back_to_history_kb(), disable_web_page_preview=True)
    except Exception as e:
        logger.error("Ошибка в cb_history_sites: %s", e, exc_info=True)
    finally:
        await call.answer()

@router.callback_query(F.data == "history_tg")
async def cb_history_tg(call: CallbackQuery):
    logger.info("Пользователь %s запросил историю Telegram", call.from_user.id)
    try:
        s = {
            "ссылка": "https://t.me/technonikol/456",
            "что_делают": "Планируют представлять стенды на выставках",
            "компания": "ТехноНиколь",
            "дата": "Апрель 2027"
        }
        text = (
            "📊 <b>История за сутки</b>\n\n"
            f"Ссылка на пост: <b>{s['ссылка']}</b>\n"
            f"Что делают: <b>{s['что_делают']}</b>\n"
            f"Компания: <b>{s['компания']}</b>\n"
            f"Дата: <b>{s['дата']}</b>\n"
        )
        await call.message.edit_text(text, reply_markup=back_to_history_kb(), disable_web_page_preview=True)
    except Exception as e:
        logger.error("Ошибка в cb_history_tg: %s", e, exc_info=True)
    finally:
        await call.answer()

@router.callback_query(F.data == "history_vk")
async def cb_history_vk(call: CallbackQuery):
    logger.info("Пользователь %s запросил историю ВК", call.from_user.id)
    try:
        s = {
            "ссылка": "https://vk.com/wall-12345_678",
            "что_делают": "Открытие нового завода в Московской области",
            "компания": "ТехноНиколь",
            "дата": "15 мая 2024"
        }
        text = (
            "📊 <b>История за сутки</b>\n\n"
            f"Ссылка на пост: <b>{s['ссылка']}</b>\n"
            f"Что делают: <b>{s['что_делают']}</b>\n"
            f"Компания: <b>{s['компания']}</b>\n"
            f"Дата: <b>{s['дата']}</b>\n"
        )
        await call.message.edit_text(text, reply_markup=back_to_history_kb(), disable_web_page_preview=True)
    except Exception as e:
        logger.error("Ошибка в cb_history_vk: %s", e, exc_info=True)
    finally:
        await call.answer()

# ==========================================
# ЛОГИКА ЗАПУСКА СКАУТЕРА (Новое)
# ==========================================

async def run_scout_agent(chat_id: int, bot: Bot):
    """Фоновая задача: отправляет запрос нейросети и сохраняет результат в БД."""
    logger.info("[SCOUT] Начало работы фоновой задачи. Отправка запроса к RouterAI...")
    try:
        # Отправляем запрос модели
        response = await ai_client.chat.completions.create(
            model=ROUTERAI_MODEL, 
            messages=[
                {"role": "system", "content": SCOUT_SYSTEM_PROMPT},
                {"role": "user", "content": "Найди 3 свежих анонса от российских компаний об участии в выставках или запуске производств."}
            ],
            response_format={"type": "json_object"}
        )
        
        # ЛОГИРУЕМ РАСХОД ТОКЕНОВ И МОДЕЛЬ
        usage = response.usage
        logger.info(
            f"[SCOUT] Ответ получен. Модель: {response.model}. "
            f"Токенов: вход={usage.prompt_tokens}, выход={usage.completion_tokens}, всего={usage.total_tokens}"
        )
        
        raw_content = response.choices[0].message.content
        logger.info(f"[SCOUT] Сырой ответ от ИИ: {raw_content}")
        
        try:
            # Чистим от markdown-тегов, если они есть
            clean_json = raw_content.strip().replace("```json", "").replace("```", "")
            findings = json.loads(clean_json)
            
            if not isinstance(findings, list):
                logger.warning("[SCOUT] ИИ вернул объект вместо массива. Оборачиваем в список.")
                findings = [findings]
                
            saved_count = 0
            for item in findings:
                company = item.get("company_name", "Неизвестно")
                url = item.get("source_url", "")
                
                # Вызываем функцию сохранения из databasefile.py
                saved = await save_scout_finding(
                    company_name=company,
                    event_description=item.get("event_description"),
                    source_url=url,
                    source_type=item.get("source_type", "website"),
                    event_date=item.get("event_date")
                )
                if saved:
                    saved_count += 1
                    logger.info(f"[SCOUT] Лид сохранен: {company} ({url})")
                else:
                    logger.warning(f"[SCOUT] Лид НЕ сохранен (возможно, дубликат): {company} ({url})")
                    
            logger.info(f"[SCOUT] Завершено. Успешно сохранено новых лидов: {saved_count} из {len(findings)}")
            
            # Уведомляем пользователя
            await bot.send_message(
                chat_id, 
                f"✅ <b>Поиск завершен!</b>\nСкаутер нашел и сохранил новых лидов: <b>{saved_count}</b>.\nПосмотреть их можно в разделе История."
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"[SCOUT] Ошибка парсинга JSON от ИИ: {e}. Сырой ответ: {raw_content}", exc_info=True)
            await bot.send_message(chat_id, "⚠️ Нейросеть вернула некорректный формат данных. Ошибка залогирована.")
            
    except Exception as e:
        logger.error(f"[SCOUT] Критическая ошибка при работе с RouterAI: {e}", exc_info=True)
        await bot.send_message(chat_id, "⚠️ Ошибка при запросе к нейросети. Проверьте логи.")

@router.callback_query(F.data == "start_search")
async def cb_start_search(call: CallbackQuery):
    logger.info("Пользователь %s нажал 'Запустить поиск'", call.from_user.id)
    try:
        is_searching_now = False 
        
        if is_searching_now:
            text = "⏳ <b>Поиск ведется сейчас!</b>\n\nПожалуйста, подождите, идет обработка данных."
            await call.answer(text, show_alert=True)
        else:
            text = "🚀 <b>Поиск запущен!</b>\n\nКак только появятся результаты, они отобразятся в истории."
            await call.answer(text, show_alert=True)
            
            # Запускаем скрипт в фоне, передавая chat_id и объект бота
            asyncio.create_task(run_scout_agent(call.message.chat.id, call.bot))
            
    except Exception as e:
        logger.error("Ошибка в cb_start_search: %s", e, exc_info=True)
        await call.answer("Ошибка при запуске поиска", show_alert=True)

@router.callback_query(F.data == "back")
async def cb_back(call: CallbackQuery):
    logger.info("Пользователь %s вернулся в главное меню", call.from_user.id)
    text = f"👋 <b>{call.from_user.full_name}</b>, вы в главном меню.\n\nВыберите действие:"
    try:
        await call.message.edit_text(text, reply_markup=main_menu_kb())
    except Exception as e:
        logger.error("Ошибка в cb_back: %s", e, exc_info=True)
    finally:
        await call.answer()

@router.message()
async def catch_all_messages(message: Message):
    logger.warning("Пользователь %s (@%s) отправил неизвестное сообщение: %s", 
                   message.from_user.id, message.from_user.username, message.text)
    await message.answer("Я пока не понимаю эту команду. Воспользуйтесь меню /start")