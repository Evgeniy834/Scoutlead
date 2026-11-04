import asyncio
import logging
import os
import datetime
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from configfile import BOT_TOKEN, ADMIN_IDS
from databasefile import init_db
from handlersfile import router, run_scout_agent
import state

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
os.makedirs("logs", exist_ok=True)
log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler("logs/bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)
logging.getLogger("aiogram").setLevel(logging.WARNING)
logging.getLogger("aiosqlite").setLevel(logging.WARNING)


# ========== ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК ==========
async def global_error_handler(event: types.ErrorEvent):
    logger.error("НЕОБРАБОТАННАЯ ОШИБКА: %s", event.exception, exc_info=event.exception)
    update = event.update
    if update.message:
        try:
            await update.message.answer("⚠️ Произошла внутренняя ошибка.")
        except TelegramAPIError:
            pass
    for admin_id in ADMIN_IDS:
        try:
            await event.update.bot.send_message(admin_id, f"🚨 <b>Упал бот!</b>\n\n<code>{str(event.exception)[:1000]}</code>")
        except TelegramAPIError:
            pass
    return True


# ========== ПЛАНИРОВЩИК (ЖДЕМ 5 МИНУТ) ==========
async def scheduler_loop(bot: Bot, chat_id: int):
    # Устанавливаем время ПЕРВОГО запуска на 5 минут вперед
    state.next_run_time = datetime.datetime.now() + datetime.timedelta(minutes=5)
    
    print("\n⏳ Планировщик запущен. Ждем 5 минут до первого автоматического поиска...")
    
    while True:
        # Ждем с обратным отсчетом
        while datetime.datetime.now() < state.next_run_time:
            remaining = state.next_run_time - datetime.datetime.now()
            total_seconds = int(remaining.total_seconds())
            if total_seconds < 0:
                total_seconds = 0
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            # Выводим таймер в одну строку
            print(f"\r⏳ До следующего запуска: {hours:02d}:{minutes:02d}:{seconds:02d}", end="")
            await asyncio.sleep(1)
        
        print("\n🚀 Бот начал работу по расписанию...")
        
        # СРАЗУ ставим время следующего запуска (снова на 5 минут)
        state.next_run_time = datetime.datetime.now() + datetime.timedelta(minutes=5)
        
        # Запускаем поиск в фоне
        asyncio.create_task(run_scout_agent(chat_id, bot))
        
        # Небольшая пауза, чтобы таймер успел обновиться перед следующим циклом
        await asyncio.sleep(1)


# ========== ЗАПУСК ==========
async def main():
    logger.info("Инициализация бота...")
    await init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    dp.errors.register(global_error_handler)

    logger.info("Бот успешно запущен и готов к работе!")

    # Принудительно делаем chat_id числом (лечит ошибку chat not found)
    chat_id = int(ADMIN_IDS[0]) if ADMIN_IDS else None
    
    if chat_id:
        asyncio.create_task(scheduler_loop(bot, chat_id))
        await asyncio.sleep(1)
        print("\n💡 ВАЖНО: Если вы видите ошибку 'chat not found', зайдите в бота и нажмите /start!")
    else:
        logger.warning("ADMIN_IDS не задан, автоматический запуск невозможен.")

    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical("Критический сбой: %s", e, exc_info=True)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот выключен вручную.")