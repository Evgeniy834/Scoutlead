import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
DB_PATH = os.getenv("DB_PATH", "./data/bot.db")

# Переменные для RouterAI
ROUTERAI_API_KEY = os.getenv("ROUTERAI_API_KEY")
ROUTERAI_BASE_URL = os.getenv("ROUTERAI_BASE_URL", "https://api.routerai.ru/v1")
# Читаем модель из .env (если там пусто, ставим дефолтную 0731)
ROUTERAI_MODEL = os.getenv("ROUTERAI_MODEL", "deepseek/deepseek-v4-flash-0731") 

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в .env")