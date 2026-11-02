from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_menu_kb() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="📖 Краткий мануал", callback_data="manual")],
        [InlineKeyboardButton(text="📋 Результаты", callback_data="results")],
        [InlineKeyboardButton(text="🚀 Запустить поиск", callback_data="start_search")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def back_kb() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="back")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def lead_actions_kb(lead_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data=f"lead_prev_{lead_id}"),
            InlineKeyboardButton(text="✅ Просмотрен", callback_data=f"lead_view_{lead_id}"),
            InlineKeyboardButton(text="Дальше ▶️", callback_data=f"lead_next_{lead_id}")
        ],
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="back")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)