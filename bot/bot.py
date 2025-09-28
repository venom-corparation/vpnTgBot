"""
Оптимизированная версия бота с централизованными хендлерами и middleware.
Убирает дублирование кода и улучшает масштабируемость.
"""

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
import asyncio
from datetime import datetime, timedelta
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters import Text
import logging
from logging.handlers import RotatingFileHandler

from config import BOT_TOKEN, ADMIN_IDS
from handlers import UserHandlers, AdminHandlers
from middleware import setup_middleware
from callbacks import *
from db import list_users_with_vpn, list_users_without_vpn, list_users_with_expired_vpn, was_reminder_sent, mark_reminder_sent, was_inactivity_reminder_sent, mark_inactivity_reminder_sent
from api import get_session_cached, get_client_info
# AnomalyMonitor отключен в основном боте - работает через cron скрипт

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

# Дополнительный журнал для платежей (с ротацией)
_payments_logger = logging.getLogger("payments")
if not _payments_logger.handlers:
    import os
    os.makedirs("logs", exist_ok=True)
    _handler = RotatingFileHandler("logs/payments.log", maxBytes=1_000_000, backupCount=5)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s"))
    _payments_logger.addHandler(_handler)
    _payments_logger.setLevel(logging.INFO)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# Настройка middleware
setup_middleware(dp, ADMIN_IDS)

# Инициализация хендлеров
user_handlers = UserHandlers(bot)
admin_handlers = AdminHandlers(bot)


class PromoStates(StatesGroup):
    waiting_code = State()

class SupportStates(StatesGroup):
    waiting_issue = State()

class AdminStates(StatesGroup):
    waiting_broadcast = State()
    waiting_promo = State()
    waiting_search_tg = State()


# ========== USER HANDLERS ==========

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message, state: FSMContext):
    await user_handlers.handle_start(message, state)


@dp.callback_query_handler(lambda c: c.data == BACK_MAIN, state="*")
async def handle_back_main(call: types.CallbackQuery, state: FSMContext):
    await state.finish()
    is_admin = call.from_user.id in ADMIN_IDS
    from keyboards import kb_main
    kb = kb_main(show_trial=user_handlers.compute_show_trial(call.from_user.id), is_admin=is_admin)
    text = (
        "Привет! Ты уже пользовался нашим сервисом!\n\n"
        "🔗 Персональная ссылка в разделе «Моя подписка».\n"
        "⏳ Время действия ссылки в разделе «Моя подписка».\n"
        "💰 Продленние ссылки в разделе «Оплатить».\n"
        "📖 Инструкция и приложения в разделе «Инструкция».\n\n"
        "💬 Есть вопрос или нашли ошибку - обратитесь в раздел «Поддержка»"
    ) if not user_handlers.compute_show_trial(call.from_user.id) else (
        "Добро пожаловать! Быстро, безопасно, надежно.\n\n"
        "💰 Приобрести подписку в разделе «Оплатить».\n"
        "🎁 Воспользоваться тестом по кнопке «Тест на 3 дня»\n"
        "📖 Инструкция и приложения в разделе «Инструкция»\n\n"
        "💬 Есть вопрос или нашли ошибку - обратитесь в раздел «Поддержка»"
    )
    from ui import edit_menu_text
    await edit_menu_text(call, text, kb)


@dp.callback_query_handler(lambda c: c.data == DOSSIER)
async def handle_dossier(call: types.CallbackQuery):
    await user_handlers.handle_dossier(call)


@dp.callback_query_handler(lambda c: c.data == TRIAL)
async def handle_trial(call: types.CallbackQuery):
    await user_handlers.handle_trial(call)


@dp.callback_query_handler(lambda c: c.data == BUY)
async def handle_buy(call: types.CallbackQuery):
    await user_handlers.handle_buy(call)


@dp.callback_query_handler(lambda c: c.data in (BUY_TEST, BUY_1M, BUY_3M, BUY_6M))
async def handle_buy_plan(call: types.CallbackQuery):
    await user_handlers.handle_buy_plan(call)


@dp.callback_query_handler(lambda c: c.data == PROMO)
async def handle_promo(call: types.CallbackQuery, state: FSMContext):
    await user_handlers.handle_promo_start(call, state)


@dp.message_handler(state=PromoStates.waiting_code, content_types=types.ContentTypes.TEXT)
async def handle_promo_text(message: types.Message, state: FSMContext):
    await user_handlers.handle_promo_text(message, state)


@dp.callback_query_handler(lambda c: c.data == GUIDE)
async def handle_guide(call: types.CallbackQuery):
    await user_handlers.handle_guide(call)


@dp.callback_query_handler(lambda c: c.data == GUIDE_PC)
async def handle_guide_pc(call: types.CallbackQuery):
    await user_handlers.handle_guide_detail(call, "pc")


@dp.callback_query_handler(lambda c: c.data == GUIDE_MOBILE)
async def handle_guide_mobile(call: types.CallbackQuery):
    await user_handlers.handle_guide_detail(call, "mobile")

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("pay_check:"), state="*")
async def handle_pay_check(call: types.CallbackQuery, state: FSMContext):
    try:
        payment_id = (call.data or "").split(":", 1)[1]
    except Exception:
        payment_id = ""
    await user_handlers.handle_pay_check(call, payment_id)

@dp.pre_checkout_query_handler(lambda q: True)
async def pre_checkout_handler(query: types.PreCheckoutQuery):
    await user_handlers.handle_pre_checkout(query)

@dp.message_handler(content_types=types.ContentTypes.SUCCESSFUL_PAYMENT)
async def successful_payment_handler(message: types.Message):
    await user_handlers.handle_successful_payment(message)


@dp.callback_query_handler(lambda c: c.data == SUPPORT)
async def handle_support(call: types.CallbackQuery, state: FSMContext):
    await user_handlers.handle_support_start(call, state)


@dp.message_handler(state=SupportStates.waiting_issue, content_types=types.ContentTypes.TEXT)
async def handle_support_text(message: types.Message, state: FSMContext):
    await user_handlers.handle_support_text(message, state)


# ========== ADMIN HANDLERS ==========

@dp.callback_query_handler(lambda c: c.data == ADMIN, state="*")
async def handle_admin(call: types.CallbackQuery, state: FSMContext):
    await admin_handlers.handle_admin(call, state)


@dp.callback_query_handler(lambda c: c.data == ADMIN_BROADCAST, state="*")
async def admin_broadcast_prompt(call: types.CallbackQuery, state: FSMContext):
    await admin_handlers.handle_broadcast_start(call, state)


@dp.message_handler(state=AdminStates.waiting_broadcast, content_types=types.ContentTypes.TEXT)
async def admin_broadcast_send(message: types.Message, state: FSMContext):
    await admin_handlers.handle_broadcast_send(message, state)


@dp.callback_query_handler(Text(equals=DISMISS))
async def dismiss_broadcast(call: types.CallbackQuery):
    await admin_handlers.handle_dismiss(call)


@dp.callback_query_handler(lambda c: c.data == ADMIN_PROMOS, state="*")
async def admin_promos_menu(call: types.CallbackQuery, state: FSMContext):
    await admin_handlers.handle_promos_menu(call, state)


@dp.callback_query_handler(lambda c: c.data == ADMIN_PROMO_NEW, state="*")
async def admin_promo_new_prompt(call: types.CallbackQuery, state: FSMContext):
    await admin_handlers.handle_promo_new_start(call, state)


@dp.message_handler(state=AdminStates.waiting_promo, content_types=types.ContentTypes.TEXT)
async def admin_promo_create(message: types.Message, state: FSMContext):
    await admin_handlers.handle_promo_create(message, state)


@dp.callback_query_handler(lambda c: c.data == ADMIN_SEARCH, state="*")
async def admin_search_prompt(call: types.CallbackQuery, state: FSMContext):
    await admin_handlers.handle_search_start(call, state)


@dp.message_handler(state=AdminStates.waiting_search_tg, content_types=types.ContentTypes.TEXT)
async def admin_search_process(message: types.Message, state: FSMContext):
    await admin_handlers.handle_search_process(message, state)


@dp.callback_query_handler(lambda c: c.data == ADMIN_STATS, state="*")
async def admin_stats_show(call: types.CallbackQuery, state: FSMContext):
    await admin_handlers.handle_stats(call, state)


@dp.callback_query_handler(lambda c: c.data == ADMIN_SYNC, state="*")
async def admin_sync_run(call: types.CallbackQuery, state: FSMContext):
    await admin_handlers.handle_sync(call, state)


# ========== UTILITY HANDLERS ==========

@dp.message_handler(state=None, content_types=types.ContentTypes.TEXT)
async def delete_stray_text(message: types.Message):
    """Удалить случайные сообщения для чистоты чата."""
    if message.text and message.text.startswith('/'):
        return
    try:
        await message.delete()
    except Exception:
        pass

if __name__ == "__main__":
    logger.info("Starting optimized VPN bot...")

    async def _periodic_worker():
        """Reminders about subscription expiry and inactivity. Runs every 6 hours to reduce API load."""
        while True:
            try:
                now = datetime.utcnow()

                # 1. Напоминания об истечении подписки
                session = get_session_cached()
                if session:
                    three_days_ms = 3 * 24 * 60 * 60 * 1000
                    users = list_users_with_vpn()
                    
                    # Обрабатываем пользователей батчами по 50 для снижения нагрузки
                    for i in range(0, len(users), 50):
                        batch = users[i:i+50]
                        for u in batch:
                            try:
                                tg = int(u.get('tg_id'))
                                email = u.get('vpn_email')
                                if not email:
                                    continue
                                
                                # Получаем информацию о клиенте (с кэшированием)
                                inbound, client = get_client_info(session, email)
                                if not client:
                                    continue
                                
                                expiry_ms = int(client.get('expiryTime') or 0)
                                if expiry_ms <= 0:
                                    continue
                                
                                now_ms = int(now.timestamp() * 1000)
                                delta = expiry_ms - now_ms
                                
                                # Напоминание за 3 дня (точное время)
                                if 0 < delta <= three_days_ms and not was_reminder_sent(tg, expiry_ms, '3d'):
                                    remaining_days = max(1, int(delta // (24*60*60*1000)))
                                    remaining_hours = int((delta % (24*60*60*1000)) // (60*60*1000))
                                    
                                    if remaining_days == 1:
                                        text = f"⏰ Напоминание: доступ истекает через {remaining_hours} ч.\n\nПродлите подписку в разделе «Оплатить»."
                                    else:
                                        text = f"⏰ Напоминание: доступ истекает через {remaining_days} дн.\n\nПродлите подписку в разделе «Оплатить»."
                                    
                                    kb = types.InlineKeyboardMarkup().add(
                                        types.InlineKeyboardButton("OK", callback_data=DISMISS)
                                    )
                                    try:
                                        await bot.send_message(tg, text, reply_markup=kb)
                                        mark_reminder_sent(tg, expiry_ms, '3d')
                                    except Exception:
                                        pass
                                
                                # Уведомление при истечении (в день истечения)
                                elif delta <= 0 and not was_reminder_sent(tg, expiry_ms, 'expired'):
                                    text = "❌ Ваша подписка истекла!\n\nПродлите доступ в разделе «Оплатить», чтобы продолжить пользоваться VPN."
                                    kb = types.InlineKeyboardMarkup().add(
                                        types.InlineKeyboardButton("OK", callback_data=DISMISS)
                                    )
                                    try:
                                        await bot.send_message(tg, text, reply_markup=kb)
                                        mark_reminder_sent(tg, expiry_ms, 'expired')
                                    except Exception:
                                        pass
                            except Exception:
                                continue
                        
                        # Небольшая пауза между батчами
                        await asyncio.sleep(1)

                # 2. Уведомления о неактивности (пользователи без VPN)
                inactive_users = list_users_without_vpn()
                for u in inactive_users:
                    try:
                        tg = int(u.get('tg_id'))
                        date_registered = u.get('date_registered')
                        if not date_registered:
                            continue
                        
                        # Проверяем, прошло ли 2 дня с регистрации
                        from datetime import datetime
                        try:
                            reg_date = datetime.fromisoformat(date_registered.replace('Z', '+00:00'))
                            days_since_reg = (now - reg_date.replace(tzinfo=None)).days
                            
                            # Отправляем уведомление через 2 дня после регистрации
                            if days_since_reg == 2 and not was_inactivity_reminder_sent(tg, days_since_reg):
                                text = (
                                    f"🤔 Что-то не понравилось в нашем сервисе?\n\n"
                                    f"Вы зарегистрировались {days_since_reg} дн. назад, но не активировали VPN.\n"
                                    f"Возможно, у вас есть вопросы или предложения?\n\n"
                                    f"💬 Напишите в «Поддержку» — мы поможем!\n"
                                    f"🎁 Или попробуйте бесплатный тест на 3 дня."
                                )
                                kb = types.InlineKeyboardMarkup().add(
                                    types.InlineKeyboardButton("OK", callback_data=DISMISS)
                                )
                                try:
                                    await bot.send_message(tg, text, reply_markup=kb)
                                    mark_inactivity_reminder_sent(tg, days_since_reg)
                                except Exception:
                                    pass
                        except ValueError:
                            # Если не удалось распарсить дату, пропускаем
                            continue
                    except Exception:
                        continue

                # 3. Уведомления о неактивности после истечения (пользователи с истекшей подпиской)
                expired_users = list_users_with_expired_vpn()
                for u in expired_users:
                    try:
                        tg = int(u.get('tg_id'))
                        email = u.get('vpn_email')
                        if not email:
                            continue
                        
                        # Получаем информацию о клиенте
                        inbound, client = get_client_info(session, email)
                        if not client:
                            continue
                        
                        expiry_ms = int(client.get('expiryTime') or 0)
                        if expiry_ms <= 0:
                            continue
                        
                        now_ms = int(now.timestamp() * 1000)
                        delta = expiry_ms - now_ms
                        
                        # Если подписка истекла
                        if delta <= 0:
                            days_expired = abs(int(delta // (24*60*60*1000)))
                            
                            # Отправляем уведомление через 2 дня после истечения
                            if days_expired == 2 and not was_inactivity_reminder_sent(tg, f"expired_{days_expired}"):
                                text = (
                                    f"🤔 Что-то не понравилось в нашем сервисе?\n\n"
                                    f"Ваша подписка истекла {days_expired} дн. назад, но вы не продлили.\n"
                                    f"Возможно, у вас есть вопросы или предложения?\n\n"
                                    f"💬 Напишите в «Поддержку» — мы поможем!\n"
                                    f"💰 Продлите подписку в разделе «Оплатить»."
                                )
                                kb = types.InlineKeyboardMarkup().add(
                                    types.InlineKeyboardButton("OK", callback_data=DISMISS)
                                )
                                try:
                                    await bot.send_message(tg, text, reply_markup=kb)
                                    mark_inactivity_reminder_sent(tg, f"expired_{days_expired}")
                                except Exception:
                                    pass
                    except Exception:
                        continue

                # Запускаем каждые 6 часов вместо каждого часа для снижения нагрузки
                await asyncio.sleep(6 * 3600)  # 6 часов
            except Exception as e:
                logger.warning("Periodic worker error: %s", e)
                await asyncio.sleep(1800)  # 30 минут при ошибке

    async def _on_startup(_: Dispatcher):
        # Инициализируем XUI сессию один раз при старте (не на каждом /start)
        try:
            get_session_cached()
        except Exception:
            pass
        asyncio.create_task(_periodic_worker())

    executor.start_polling(dp, skip_updates=True, on_startup=_on_startup)
