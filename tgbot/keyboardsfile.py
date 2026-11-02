from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_menu_kb() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="📖 Краткий мануал", callback_data="manual")],
        [InlineKeyboardButton(text="📊 История (за 24ч.)", callback_data="history")],
        [InlineKeyboardButton(text="🚀 Запустить поиск", callback_data="start_search")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def history_menu_kb() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="🌐 Результаты сайта", callback_data="history_sites")],
        [InlineKeyboardButton(text="📱 Результаты ВК", callback_data="history_vk")],
        [InlineKeyboardButton(text="✈️ Результаты Телеграмме", callback_data="history_tg")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def back_to_history_kb() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="◀️ Назад к выбору источника", callback_data="history")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def back_kb() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)