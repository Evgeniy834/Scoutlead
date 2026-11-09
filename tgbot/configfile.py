import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "./data/bot.db")

# Переменные для RouterAI
ROUTERAI_API_KEY = os.getenv("ROUTERAI_API_KEY")
ROUTERAI_BASE_URL = os.getenv("ROUTERAI_BASE_URL", "https://api.routerai.ru/v1")
# Читаем модели из .env (если там пусто, ставим дефолтную)
SCOUTER_MODEL = os.getenv("SCOUTER_MODEL", "perplexity/sonar-pro-search")
ANALYST_MODEL = os.getenv("ANALYST_MODEL", "anthropic/claude-sonnet-5") 

BOT_PASSWORD = os.getenv("BOT_PASSWORD", "131131")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в .env")