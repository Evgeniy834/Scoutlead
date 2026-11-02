import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from configfile import BOT_TOKEN, ADMIN_IDS
from databasefile import init_db
from handlersfile import router


os.makedirs("logs", exist_ok=True)

log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    handlers=[
        logging.StreamHandler(),  
        RotatingFileHandler(
            "logs/bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        ),  
    ],
)
logger = logging.getLogger(__name__)


logging.getLogger("aiogram").setLevel(logging.WARNING)
logging.getLogger("aiosqlite").setLevel(logging.WARNING)



async def global_error_handler(event: types.ErrorEvent):
    logger.error(
        "НЕОБРАБОТАННАЯ ОШИБКА: %s", 
        event.exception, 
        exc_info=event.exception
    )
    
    update = event.update
    if update.message:
        try:
            await update.message.answer("⚠️ Произошла внутренняя ошибка. Мы уже чиним!")
        except TelegramAPIError:
            pass
            
    for admin_id in ADMIN_IDS:
        try:
            await event.update.bot.send_message(
                admin_id, 
                f"🚨 <b>Упал бот!</b>\n\n<code>{str(event.exception)[:1000]}</code>"
            )
        except TelegramAPIError:
            pass

    return True  


# ========== ЗАПУСК ==========
async def main():
    logger.info("Инициализация бота...")
    await init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    
    dp.include_router(router)
    
    
    dp.errors.register(global_error_handler)

    logger.info("Бот успешно запущен и готов к работе!")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical("Критический сбой при запуске polling: %s", e, exc_info=True)
    finally:
        await bot.session.close()
        logger.info("Бот остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот выключен вручную (Ctrl+C).")