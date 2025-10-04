from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from callbacks import (
    ADMIN, ADMIN_BROADCAST, ADMIN_SEARCH, ADMIN_STATS, ADMIN_PROMOS, ADMIN_PROMO_NEW, ADMIN_SYNC,
    BACK_MAIN, BUY, BUY_SERVICE, BUY_PLAN, PROMO, GUIDE, GUIDE_PC, GUIDE_MOBILE,
    DOSSIER, TRIAL, SUPPORT
)

from tariffs import TariffService, all_services


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
    """Keyboard for selecting a tariff service (Standard / Обход ...)."""
    kb = InlineKeyboardMarkup(row_width=1)
    for service in all_services():
        kb.add(
            InlineKeyboardButton(
                f"{service.name}",
                callback_data=f"{BUY_SERVICE}:{service.key}"
            )
        )
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data=BACK_MAIN))
    return kb


def kb_buy_plans(service: TariffService, is_admin: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    for plan in service.plans_for_user(is_admin):
        kb.add(
            InlineKeyboardButton(
                plan.label,
                callback_data=f"{BUY_PLAN}:{service.key}:{plan.key}"
            )
        )
    kb.add(InlineKeyboardButton("⬅️ К тарифам", callback_data=BUY))
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
    kb.add(InlineKeyboardButton("🧾 Логи (последние)", callback_data="admin_logs"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data=BACK_MAIN))
    return kb


def kb_payment(url: str, pay_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("Оплатить в ЮKassa", url=url))
    kb.add(InlineKeyboardButton("Я оплатил — проверить", callback_data=f"pay_check:{pay_id}"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data=BACK_MAIN))
    return kb

