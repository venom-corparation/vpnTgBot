from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from callbacks import (
    ADMIN, ADMIN_BROADCAST, ADMIN_SEARCH, ADMIN_STATS, ADMIN_PROMOS, ADMIN_PROMO_NEW, ADMIN_SYNC,
    BACK_MAIN, BUY, BUY_TEST, BUY_1M, BUY_3M, BUY_6M, PROMO, GUIDE, GUIDE_PC, GUIDE_MOBILE,
    DOSSIER, TRIAL, SUPPORT
)


def kb_main(show_trial: bool, is_admin: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("💳 Моя Подписка", callback_data=DOSSIER))
    if show_trial:
        kb.add(InlineKeyboardButton("🎁 Тест на 3 дня", callback_data=TRIAL))
    kb.row(InlineKeyboardButton("💰 Оплатить", callback_data=BUY), InlineKeyboardButton("🎫 Промокод", callback_data=PROMO))
    kb.row(InlineKeyboardButton("📖 Инструкция", callback_data=GUIDE), InlineKeyboardButton("💬 Поддержка", callback_data=SUPPORT))
    if is_admin:
            kb.add(InlineKeyboardButton("⚙️ Админка", callback_data=ADMIN))
    return kb


def kb_buy_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    if is_admin:
        kb.add(InlineKeyboardButton("🧪 Тест — 1₽ (1 день)", callback_data=BUY_TEST))
    kb.add(InlineKeyboardButton("1 месяц — 149₽", callback_data=BUY_1M))
    kb.add(InlineKeyboardButton("3 месяца — 369₽", callback_data=BUY_3M))
    kb.add(InlineKeyboardButton("6 месяца — 649₽", callback_data=BUY_6M))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data=BACK_MAIN))
    return kb


def kb_promo_back() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data=BACK_MAIN))
    return kb


def kb_guide() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("ПК", callback_data=GUIDE_PC))
    kb.add(InlineKeyboardButton("Android / iOS", callback_data=GUIDE_MOBILE))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data=BACK_MAIN))
    return kb


def admin_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("📢 Рассылка", callback_data=ADMIN_BROADCAST))
    kb.add(InlineKeyboardButton("🔍 Поиск по ID", callback_data=ADMIN_SEARCH))
    kb.add(InlineKeyboardButton("📊 Статистика", callback_data=ADMIN_STATS))
    kb.add(InlineKeyboardButton("🎫 Промокоды", callback_data=ADMIN_PROMOS))
    kb.add(InlineKeyboardButton("🔄 Синхронизация", callback_data=ADMIN_SYNC))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data=BACK_MAIN))
    return kb


def kb_payment(url: str, pay_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("Оплатить в ЮKassa", url=url))
    kb.add(InlineKeyboardButton("Я оплатил — проверить", callback_data=f"pay_check:{pay_id}"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data=BACK_MAIN))
    return kb

