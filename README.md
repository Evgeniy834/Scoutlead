# 🤖 LeadScouter 24/7

**LeadScouter** — автономный Telegram-бот с двумя ИИ-агентами для проактивного B2B-маркетинга. Бот мониторит российский сегмент интернета (сайты, Telegram, ВКонтакте), находит анонсы офлайн-событий (выставок, конференций, запусков заводов) и формирует чистую базу лидов.

## 🌟 Фичи
- **Два агента:** Скаутер (ищет) и Аналитик (проверяет и чистит мусор).
- **Автономность:** цикл каждые 12 часов + принудительный запуск.
- **Фильтрация:** только домены `.ru`, `t.me`, `vk.com`; отсев прошедших дат и битых ссылок (404).
- **UI:** удобные карточки лидов с кнопками «Назад/Дальше/Просмотрен».
- **Безопасность:** доступ по паролю, логирование всех действий.

## 🛠 Стек
Python 3.11+, aiogram 3.x, aiosqlite, openai (RouterAI), httpx, BeautifulSoup4.

## 🚀 Установка
```bash
git clone https://github.com/your-username/leadscouter.git
cd leadscouter
python3 -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
 
===============================================================
    Запуск на фоне + просмотор сесии/логов + остановка сессии
===============================================================
nohup python startfile.py > bot_out.log 2>&1 &
ps aux | grep startfile.py
tail -f bot_out.log
pkill -f startfile.py
