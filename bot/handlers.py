"""
Централизованные хендлеры для Telegram бота.
Убирает дублирование кода и улучшает масштабируемость.
"""

from aiogram import types, Bot
import html
import asyncio
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice
from aiogram.utils.exceptions import MessageNotModified
import logging
import os

from config import ADMIN_IDS, PROVIDER_TOKEN, CURRENCY, USE_YOOKASSA
from payments import create_redirect_payment, get_payment_status
from db import save_payment, update_payment_status, get_payment, mark_payment_applied
from api import get_session_cached, check_if_client_exists, get_client_info, add_client_days, extend_client_days, generate_vless_link
from db import upsert_user_on_start, set_vpn_email, get_user_by_tg, redeem_promo, add_promo, list_users, count_users, count_users_with_vpn, count_promos, sum_promo_uses, list_promos, sync_users_with_xui
from keyboards import kb_main, kb_buy_menu, kb_buy_plans, kb_promo_back, kb_guide, admin_kb, kb_payment
from ui import edit_menu_text, edit_menu_text_pm
from callbacks import ADMIN_PROMOS
from tariffs import TariffService, all_services, get_service, get_plan, DEFAULT_SERVICE_KEY, auto_assign_services


class MessageHandler:
    """Централизованный обработчик сообщений с общими паттернами."""
    
    def __init__(self, bot: Bot):
        self.bot = bot
    
    async def safe_edit_message(self, chat_id: int, msg_id: int, text: str, 
                              reply_markup: InlineKeyboardMarkup = None, 
                              parse_mode: str = "Markdown") -> bool:
        """Безопасное редактирование сообщения с обработкой ошибок."""
        try:
            await self.bot.edit_message_text(text, chat_id, msg_id, parse_mode=parse_mode)
            if reply_markup:
                await self.bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=reply_markup)
            return True
        except MessageNotModified:
            return True
        except Exception:
            return False
    
    async def get_menu_data(self, state: FSMContext, message: types.Message = None, call: types.CallbackQuery = None):
        """Получить chat_id и msg_id приоритезируя сохранённый id меню из state."""
        data = await state.get_data()
        chat_id = data.get("menu_chat_id")
        msg_id = data.get("menu_msg_id")
        if chat_id and msg_id:
            return chat_id, msg_id
        if call:
            return call.message.chat.id, call.message.message_id
        if message:
            return message.chat.id, message.message_id
        return None, None
    
    async def delete_user_message(self, message: types.Message):
        """Удалить сообщение пользователя для чистоты чата."""
        try:
            await message.delete()
        except Exception:
            pass
    
    async def show_loading_feedback(self, chat_id: int, msg_id: int, text: str = "Обрабатываю..."):
        """Показать индикатор загрузки и временно убрать клавиатуру."""
        # убрать клавиатуру на время обработки
        try:
            await self.bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
        except Exception:
            pass
        await self.safe_edit_message(chat_id, msg_id, text, parse_mode="Markdown")
    
    async def handle_vpn_operation(
        self,
        user_id: int,
        days: int,
        service_key: str = DEFAULT_SERVICE_KEY,
        operation_name: str = "операция",
    ) -> bool:
        """Универсальная обработка VPN операций (добавление/продление дней)."""
        service = get_service(service_key) or get_service(DEFAULT_SERVICE_KEY)
        if not service:
            logging.error("Unknown service %s for VPN operation %s", service_key, operation_name)
            return False

        session = get_session_cached()
        if not session:
            return False

        primary_email = service.email_for_user(user_id)
        if not self._apply_service_days(session, user_id, days, service):
            logging.error(
                "Не удалось применить %s (%s) для пользователя %s",
                service.key,
                operation_name,
                user_id,
            )
            return False

        extras_ok = True
        for extra_service in auto_assign_services():
            if extra_service.key == service.key:
                continue
            if not self._apply_service_days(session, user_id, days, extra_service):
                logging.error(
                    "Не удалось выдать доп. сервис %s пользователю %s (%s)",
                    extra_service.key,
                    user_id,
                    operation_name,
                )
                extras_ok = False

        if not extras_ok:
            return False

        if service_key == DEFAULT_SERVICE_KEY:
            set_vpn_email(user_id, primary_email)
        return True
    
    def compute_show_trial(self, user_id: int) -> bool:
        """Вычислить, показывать ли кнопку теста."""
        user = get_user_by_tg(user_id)
        return not bool(user and user.get("vpn_email"))
    
    def is_admin(self, user_id: int) -> bool:
        """Проверить, является ли пользователь админом."""
        return user_id in ADMIN_IDS

    def _apply_service_days(self, session, user_id: int, days: int, service: TariffService) -> bool:
        """Создать или продлить клиента в указанном сервисе на нужное число дней."""
        email = service.email_for_user(user_id)
        inbound_id = service.inbound_id
        if check_if_client_exists(session, email, inbound_id=inbound_id):
            return extend_client_days(session, user_id, days, inbound_id=inbound_id, email=email)

        result = add_client_days(session, user_id, days, inbound_id=inbound_id, email=email)
        if isinstance(result, dict):
            return bool(result.get("client_id"))
        return bool(result)


class UserHandlers(MessageHandler):
    """Хендлеры для обычных пользователей."""

    @staticmethod
    def _split_plan_code(plan_code: str) -> tuple[str, str]:
        if not plan_code:
            return DEFAULT_SERVICE_KEY, ""
        if ":" in plan_code:
            service_key, plan_key = plan_code.split(":", 1)
            return service_key or DEFAULT_SERVICE_KEY, plan_key or ""
        return DEFAULT_SERVICE_KEY, plan_code
    
    async def handle_start(self, message: types.Message, state: FSMContext):
        """Обработчик команды /start."""
        await state.finish()
        tg = message.from_user
        upsert_user_on_start(
            tg_id=tg.id,
            username=tg.username,
            first_name=tg.first_name,
            last_name=tg.last_name,
        )

        # --- Синхронизация БД с XUI ---
        session = get_session_cached()
        if session:
            if check_if_client_exists(session, tg.id):
                # Пользователь есть в XUI - устанавливаем vpn_email
                set_vpn_email(tg.id, str(tg.id))
            else:
                # Пользователя нет в XUI - очищаем vpn_email если был
                user = get_user_by_tg(tg.id)
                if user and user.get("vpn_email"):
                    set_vpn_email(tg.id, None)
                    logging.info(f"Синхронизация: очищен vpn_email для пользователя {tg.id}")
        # ---------------------------------

        is_vpn = bool(get_user_by_tg(tg.id) and get_user_by_tg(tg.id).get("vpn_email"))
        is_admin = self.is_admin(tg.id)
        show_trial = self.compute_show_trial(tg.id)
        kb = kb_main(show_trial=show_trial, is_admin=is_admin)

        if is_vpn:
            text = (
                "Привет! Ты уже пользовался нашим сервисом!\n\n"
                "🔗 Персональная ссылка в разделе «Моя подписка».\n"
                "⏳ Время действия ссылки в разделе «Моя подписка».\n"
                "💰 Продленние ссылки в разделе «Оплатить».\n"
                "📖 Инструкция и приложения в разделе «Инструкция».\n\n"
                "💬 Есть вопрос или нашли ошибку - обратитесь в раздел «Поддержка»"
            )
        else:
            text = (
                "Добро пожаловать! Быстро, безопасно, надежно.\n\n"
                "💰 Приобрести подписку в разделе «Оплатить».\n"
                "🎁 Воспользоваться тестом по кнопке «Тест на 3 дня»"
                "📖 Инструкция и приложения в разделе «Инструкция»\n\n"
                "💬 Есть вопрос или нашли ошибку - обратитесь в раздел «Поддержка»"
            )
        sent = await message.answer(text, reply_markup=kb)
        await state.update_data(menu_msg_id=sent.message_id)

    async def handle_dossier(self, call: types.CallbackQuery):
        """Показать досье пользователя."""
        session = get_session_cached()
        if not session:
            await call.answer("Сервер спит.", show_alert=True)
            return
        
        user_id = call.from_user.id
        services_info = []
        is_admin = self.is_admin(user_id)

        for service in all_services(include_hidden=True):
            email = service.email_for_user(user_id)
            inbound, client = get_client_info(session, email, inbound_id=service.inbound_id)
            if inbound and client:
                services_info.append((service, inbound, client))
            elif service.key == DEFAULT_SERVICE_KEY:
                user = get_user_by_tg(user_id)
                if user and user.get("vpn_email"):
                    set_vpn_email(user_id, None)
                    logging.info(f"Синхронизация: очищен vpn_email для пользователя {user_id}")

        kb = kb_main(show_trial=self.compute_show_trial(user_id), is_admin=is_admin)

        if not services_info:
            await edit_menu_text(call, "Вы еще не оформляли подписку", kb)
            return

        def fmt_exp(ms):
            try:
                ms = int(ms)
                if ms == 0:
                    return "бесконечно"
                from datetime import datetime
                return datetime.fromtimestamp(ms / 1000).strftime("%d.%m.%Y %H:%M")
            except Exception:
                return str(ms)

        sections = [f"Профиль: @{call.from_user.username or '-'}"]
        for service, inbound, client in services_info:
            link = generate_vless_link(inbound, client)
            expiry = fmt_exp(client.get('expiryTime', 0))
            extra = " (бессрочно)" if expiry == "бесконечно" else ""
            sections.append(
                f"<b>{service.name}</b>\n"
                f"Действует до: {expiry}{extra}\n"
                f"Ссылка:\n<pre><code>{html.escape(link)}</code></pre>"
            )

        text = "\n\n".join(sections)
        await edit_menu_text_pm(call, text, kb, parse_mode="HTML")

    async def handle_trial(self, call: types.CallbackQuery):
        """Выдать тестовый доступ на 3 дня."""
        session = get_session_cached()
        if not session:
            await call.answer("Сервер отдыхает.", show_alert=True)
            return
        
        if not self.compute_show_trial(call.from_user.id):
            await call.answer("Вы уже брали тестовый период", show_alert=True)
            return
        
        ok = await self.handle_vpn_operation(
            call.from_user.id,
            days=3,
            service_key=DEFAULT_SERVICE_KEY,
            operation_name="тестовый доступ",
        )
        if ok:
            is_admin = self.is_admin(call.from_user.id)
            kb = kb_main(show_trial=False, is_admin=is_admin)
            await edit_menu_text(call, "Выдан тестовый доступ на 3 дня.\nСсылка доступна в разделе «Моя подписка».", kb)
        else:
            await call.answer("Ошибка. Попробуйте позже.", show_alert=True)

    async def handle_buy(self, call: types.CallbackQuery):
        """Показать меню покупки."""
        is_admin = self.is_admin(call.from_user.id)
        lines = ["Выберите услугу перед оплатой:\n"]
        for service in all_services():
            lines.append(f"• *{service.name}* — {service.description}")
        lines.append("\nПосле выбора услуги появятся доступные планы и цены.")
        text = "\n".join(lines)
        await edit_menu_text(call, text, kb_buy_menu(is_admin=is_admin))

    async def handle_buy_service(self, call: types.CallbackQuery):
        """Показать планы конкретной услуги."""
        try:
            _, service_key = (call.data or "").split(":", 1)
        except ValueError:
            await call.answer("Не удалось определить услугу.", show_alert=True)
            return

        service = get_service(service_key)
        if not service:
            await call.answer("Услуга недоступна.", show_alert=True)
            return

        is_admin = self.is_admin(call.from_user.id)
        kb = kb_buy_plans(service, is_admin=is_admin)
        text = (
            f"Тариф «{service.name}».\n\n"
            f"{service.description}\n\nВыберите длительность подписки:" 
        )
        await edit_menu_text(call, text, kb)

    async def handle_buy_plan(self, call: types.CallbackQuery):
        """Обработать покупку плана выбранной услуги."""
        try:
            _, service_key, plan_key = (call.data or "").split(":", 2)
        except ValueError:
            await call.answer("Не удалось определить план.", show_alert=True)
            return

        service = get_service(service_key)
        plan = get_plan(service_key, plan_key)
        if not service or not plan:
            await call.answer("План недоступен.", show_alert=True)
            return

        if plan.admin_only and not self.is_admin(call.from_user.id):
            await call.answer("Доступ ограничен.", show_alert=True)
            return

        days = plan.days
        amount = plan.amount_minor
        plan_code = f"{service_key}:{plan_key}"
        description = f"{service.name}: доступ на {days} дней"
        is_admin = self.is_admin(call.from_user.id)

        logging.info(
            "purchase_selected: user=%s service=%s plan=%s days=%s amount_minor=%s",
            call.from_user.id,
            service_key,
            plan_key,
            days,
            amount,
        )

        if USE_YOOKASSA:
            # YooKassa Smart Payment: создаём платеж и отправляем ссылку-навигацию
            rub = amount / 100.0
            bot_user = (await self.bot.get_me()).username
            pay = create_redirect_payment(
                amount_rub=rub,
                description=description,
                bot_username=bot_user,
                user_id=call.from_user.id,
            )
            if pay and pay.get("confirmation_url"):
                url = pay["confirmation_url"]
                # Сохраняем платёж
                try:
                    save_payment(
                        payment_id=pay.get("id") or "",
                        tg_id=call.from_user.id,
                        plan=plan_code,
                        days=days,
                        amount=amount,
                        currency=CURRENCY or "RUB",
                        status=pay.get("status") or "pending",
                    )
                except Exception:
                    pass
                kb = kb_payment(url, pay.get('id') or '')
                await edit_menu_text(call, "Перейдите по ссылке для оплаты. После оплаты вернитесь в бот и нажмите ‘Я оплатил — проверить’.", kb)
            else:
                err = (pay or {}).get("error") if isinstance(pay, dict) else "unknown"
                logging.error("YooKassa payment creation failed: %s", err)
                await call.answer("Платёж недоступен. Проверьте настройки ЮKassa и попробуйте позже.", show_alert=True)
            return

        if not USE_YOOKASSA and not PROVIDER_TOKEN:
            # Если платежи не настроены — временно начисляем дни (тестовый режим)
            ok = await self.handle_vpn_operation(call.from_user.id, days, service_key=service_key)
            is_admin = self.is_admin(call.from_user.id)
            kb = kb_main(show_trial=False, is_admin=is_admin)
            await edit_menu_text(call, ("Начислено: "+str(days)+" дн. (тестовый режим)") if ok else "Ошибка. Попробуй позже.", kb)
            return

        title = f"{service.name} — {plan.days} дн."
        description_invoice = f"Оплата услуги ‘{service.name}’ на {days} дней."
        payload = f"service:{service_key};plan:{plan_key};days:{days}"
        prices = [LabeledPrice(label=plan.label, amount=amount)]

        await self.bot.send_invoice(
            chat_id=call.message.chat.id,
            title=title,
            description=description_invoice,
            payload=payload,
            provider_token=PROVIDER_TOKEN,
            currency=CURRENCY or "RUB",
            prices=prices,
            need_name=False,
            need_phone_number=False,
            need_email=False,
            is_flexible=False,
        )

    async def handle_pre_checkout(self, query: types.PreCheckoutQuery):
        try:
            await self.bot.answer_pre_checkout_query(pre_checkout_query_id=query.id, ok=True)
        except Exception:
            try:
                await self.bot.answer_pre_checkout_query(pre_checkout_query_id=query.id, ok=False, error_message="Не удалось обработать платеж. Попробуйте позже.")
            except Exception:
                pass

    async def handle_successful_payment(self, message: types.Message):
        try:
            payload = message.successful_payment.invoice_payload or ""
            parts = dict(p.split(":", 1) for p in payload.split(";") if ":" in p)
            days = int(parts.get("days", "30"))
            service_key = parts.get("service", DEFAULT_SERVICE_KEY)
        except Exception:
            days = 30
            service_key = DEFAULT_SERVICE_KEY

        sp = message.successful_payment
        charge_id = getattr(sp, "provider_payment_charge_id", "")
        total_amount = getattr(sp, "total_amount", 0)
        currency = getattr(sp, "currency", "RUB")

        ok = await self.handle_vpn_operation(message.from_user.id, days, service_key=service_key)
        is_admin = self.is_admin(message.from_user.id)
        kb = kb_main(show_trial=False, is_admin=is_admin)
        text = "Оплата получена. Доступ активирован на " + str(days) + " дн." if ok else "Оплата получена, но не удалось активировать доступ. Напишите в поддержку."
        try:
            await message.answer(text, reply_markup=kb)
        except Exception:
            pass
        # Уведомить админов о платеже (ЮKassa charge_id)
        note = (
            f"[PAYMENT] user={message.from_user.id}, days={days}, amount={total_amount} {currency}, charge_id={charge_id}"
        )
        for admin_id in ADMIN_IDS:
            try:
                await self.bot.send_message(admin_id, note)
            except Exception:
                pass

    async def handle_promo_start(self, call: types.CallbackQuery, state: FSMContext):
        """Начать ввод промокода."""
        from bot import PromoStates
        await PromoStates.waiting_code.set()
        await state.update_data(menu_chat_id=call.message.chat.id, menu_msg_id=call.message.message_id)
        await edit_menu_text(call, "Введи промокод", kb_promo_back())

    async def handle_promo_text(self, message: types.Message, state: FSMContext):
        """Обработать введенный промокод."""
        code = (message.text or "").strip()
        chat_id, msg_id = await self.get_menu_data(state, message=message)
        
        await self.delete_user_message(message)
        await self.show_loading_feedback(chat_id, msg_id, "Проверяю промокод...")
        
        info = redeem_promo(code, message.from_user.id)
        if not info.get("ok"):
            # при ошибке вернуть кнопку Назад
            await self.safe_edit_message(chat_id, msg_id, "Промокод не найден. Попробуй ещё раз", 
                                       reply_markup=kb_promo_back(), parse_mode="Markdown")
            return
        
        days = max(1, int(info.get("days", 0)))
        await self.show_loading_feedback(chat_id, msg_id, f"Код принят. Начисляю {days} дн...")
        
        session = get_session_cached()
        if not session:
            # при ошибке вернуть кнопку Назад
            await self.safe_edit_message(chat_id, msg_id, "Сервер устал. Заберёшь позже.", 
                                       reply_markup=kb_promo_back(), parse_mode="Markdown")
            return
        
        await self.handle_vpn_operation(message.from_user.id, days)
        
        await state.finish()
        is_admin = self.is_admin(message.from_user.id)
        kb = kb_main(show_trial=False, is_admin=is_admin)
        await self.safe_edit_message(chat_id, msg_id, f"Начислено: {days} дн.\nСсылка доступна в разделе «Моя подписка».", 
                                   reply_markup=kb, parse_mode="Markdown")

    async def handle_guide(self, call: types.CallbackQuery):
        """Показать инструкцию."""
        text = (
            "Инструкция по использованию:\n\n"
            "1. Нажми «Моя подписка» — там твоя персональная ссылка для подключения\n"
            "2. Вставь ссылку в приложение (ПК или мобильное)\n"
            "3. Подключайся и пользуйся\n"
            "4. Если нет доступа — возьми тестовый период или оформи подписку\n"
            "5. Промокоды активируй через соответствующую кнопку\n\n"
            "Выбери платформу для детальной инструкции:"
        )
        await edit_menu_text(call, text, kb_guide(), disable_web_page_preview=True)

    async def handle_pay_check(self, call: types.CallbackQuery, payment_id: str):
        paid = False
        status = "unknown"
        if not payment_id:
            await call.answer("Не найден платеж.", show_alert=True)
            return
        # Быстрое короткое ожидание подтверждения (опрашиваем несколько раз)
        attempts = 6
        final_status = None
        for _ in range(attempts):
            info = get_payment_status(payment_id) or {}
            if isinstance(info, dict) and info.get("error"):
                final_status = "unknown"
                paid = False
                status = "unknown"
            else:
                status = (info or {}).get("status") or "unknown"
                paid = bool((info or {}).get("paid"))
                final_status = status
            try:
                update_payment_status(payment_id, status)
            except Exception:
                pass
            if paid or status in ("succeeded", "canceled"):
                break
            try:
                await asyncio.sleep(1)
            except Exception:
                break

        if final_status == "succeeded" or (isinstance(info, dict) and info.get("paid")):
            p = get_payment(payment_id)
            if p and int(p.get("applied", 0)) == 1:
                await call.answer("Платёж уже применён.", show_alert=True)
                return
            days = int(p.get("days", 30)) if p else 30
            plan_code = (p or {}).get("plan", "") if p else ""
            service_key, _ = self._split_plan_code(plan_code)
            ok = await self.handle_vpn_operation(call.from_user.id, days, service_key=service_key)
            if p:
                try:
                    mark_payment_applied(payment_id)
                except Exception:
                    pass
            is_admin = self.is_admin(call.from_user.id)
            kb = kb_main(show_trial=False, is_admin=is_admin)
            await edit_menu_text(call, f"Оплата подтверждена. Доступ активирован на {days} дн.", kb)
        elif final_status == "canceled":
            await edit_menu_text(call, "Оплата отменена.", kb_promo_back())
        else:
            await edit_menu_text(call, "Платёж пока не подтверждён. Попробуйте позже.", kb_promo_back())

    async def handle_guide_detail(self, call: types.CallbackQuery, platform: str):
        """Показать детальную инструкцию для платформы."""
        if platform == "pc":
            text = (
                "\U0001F5A5 Подключение на ПК:\n\n"
                "1. Проверьте срок действия вашей подписки в разделе «Моя подписка» в боте. Если срок истёк — продлите или используйте промокод.\n"
                "2. Скопируйте персональную ссылку.\n"
                "3. Скачайте клиент InvisibleMan XRay: [InvisibleManXRay-x64.zip](https://github.com/InvisibleManVPN/InvisibleMan-XRayClient/releases/download/v3.2.5/InvisibleManXRay-x64.zip)\n"
                "4. Распакуйте архив и запустите InvisibleManXRay.exe.\n"
                "5. В главном окне нажмите ‘Manage server configuration’ → ‘+’ → ‘Import from link’, вставьте ссылку и нажмите ‘Import’.\n"
                "6. Включите и пользуйтесь!\n\n"
                "Если возникнут вопросы — напишите в поддержку!"
            )
        elif platform == "mobile":
            text = (
                "Подключение на телефон:\n\n"
                "1. Проверьте срок действия вашей подписки в разделе «Моя подписка» в боте. Если срок истёк — продлите или используйте промокод.\n"
                "2. Скопируйте персональную ссылку.\n"
                "3. Скачайте Hiddify:\n"
                "   • [Для iOS](https://apps.apple.com/us/app/hiddify-proxy-vpn/id6596777532?platform=iphone)\n"
                "   • [Для Android](https://play.google.com/store/apps/details?id=app.hiddify.com)\n"
                "4. Откройте Hiddify, нажмите ‘+’ в верхнем углу и выберите ‘Вставить из буфера обмена’ — профиль добавится автоматически.\n"
                "5. Включите и пользуйтесь!\n\n"
                "Важно: при необходимости удалите другие VPN-профили в настройках устройства, чтобы активировать с кнопки.\n\n"
                "Если возникнут вопросы — напишите в поддержку!"
            )
        await edit_menu_text(call, text, kb_guide(), disable_web_page_preview=True)

    async def handle_support_start(self, call: types.CallbackQuery, state: FSMContext):
        """Начать отправку сообщения в поддержку."""
        from bot import SupportStates
        await SupportStates.waiting_issue.set()
        await state.update_data(menu_chat_id=call.message.chat.id, menu_msg_id=call.message.message_id)
        await edit_menu_text(call, "Опиши проблему. Пиши текстом — без вложений", kb_promo_back())

    async def handle_support_text(self, message: types.Message, state: FSMContext):
        """Обработать сообщение в поддержку."""
        issue = (message.text or "").strip()
        chat_id, msg_id = await self.get_menu_data(state, message=message)
        
        await self.delete_user_message(message)
        
        # Отправить админам
        for admin_id in ADMIN_IDS:
            try:
                await self.bot.send_message(admin_id, f"[SUPPORT] от @{message.from_user.username or message.from_user.id} ({message.from_user.id}): {issue}")
            except Exception:
                pass
        
        await state.finish()
        kb = kb_main(show_trial=self.compute_show_trial(message.from_user.id), 
                    is_admin=self.is_admin(message.from_user.id))
        # финально показать сообщение и вернуть клавиатуру главного меню
        await self.safe_edit_message(chat_id, msg_id, "Сообщение отправлено. Ожидайте сообщения или решения проблемы. Администраторы видят каждое сообщение", 
                                   reply_markup=kb)


class AdminHandlers(MessageHandler):
    """Хендлеры для администраторов."""
    
    async def handle_admin(self, call: types.CallbackQuery, state: FSMContext):
        """Показать админ-панель."""
        if not self.is_admin(call.from_user.id):
            await call.answer("Доступ ограничен.", show_alert=True)
            return
        await state.finish()
        # Добавляем кнопку 'Логи' динамически
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"))
        kb.add(InlineKeyboardButton("🔍 Поиск по ID", callback_data="admin_search"))
        kb.add(InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"))
        kb.add(InlineKeyboardButton("🎫 Промокоды", callback_data="admin_promos"))
        kb.add(InlineKeyboardButton("🔄 Синхронизация", callback_data="admin_sync"))
        kb.add(InlineKeyboardButton("🧾 Логи (последние)", callback_data="admin_logs"))
        kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="back_main"))
        await edit_menu_text(call, "Панель управления", kb)

    async def handle_broadcast_start(self, call: types.CallbackQuery, state: FSMContext):
        """Начать рассылку."""
        if not self.is_admin(call.from_user.id):
            await call.answer("Доступ ограничен.", show_alert=True)
            return
        
        from bot import AdminStates
        await AdminStates.waiting_broadcast.set()
        await state.update_data(menu_chat_id=call.message.chat.id, menu_msg_id=call.message.message_id)
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Назад", callback_data="admin"))
        await edit_menu_text(call, "Введи сообщение для рассылки", kb)

    async def handle_broadcast_send(self, message: types.Message, state: FSMContext):
        """Отправить рассылку."""
        if not self.is_admin(message.from_user.id):
            await state.finish()
            return
        
        chat_id, msg_id = await self.get_menu_data(state, message=message)
        await self.delete_user_message(message)
        
        users = list_users(limit=100000)
        sent = 0
        for u in users:
            try:
                kb_ok = InlineKeyboardMarkup().add(InlineKeyboardButton("OK", callback_data="dismiss"))
                await self.bot.send_message(u.get("tg_id"), message.text, reply_markup=kb_ok)
                sent += 1
            except Exception:
                pass
        
        await state.finish()
        await self.safe_edit_message(chat_id, msg_id, f"Отправлено: {sent} пользователям", 
                                   reply_markup=admin_kb(), parse_mode="Markdown")

    async def handle_promos_menu(self, call: types.CallbackQuery, state: FSMContext):
        """Показать меню промокодов."""
        if not self.is_admin(call.from_user.id):
            await call.answer("Доступ ограничен.", show_alert=True)
            return
        
        await state.finish()
        promos = list_promos(active_only=True, limit=50, offset=0)
        if promos:
            lines = [f"{p['code']}: {p.get('days',0)} дн, {p['used_count']}/{p['max_uses']}" for p in promos]
            text = "Активные промокоды:\n" + "\n".join(lines)
            if len(promos) == 50:
                text += "\n... и ещё. Уточни фильтр/пагинацию при необходимости."
        else:
            text = "Активных промокодов нет."
        
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("➕ Создать промокод", callback_data="admin_promo_new"))
        kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="admin"))
        await edit_menu_text(call, text, kb)

    async def handle_promo_new_start(self, call: types.CallbackQuery, state: FSMContext):
        """Начать создание промокода."""
        if not self.is_admin(call.from_user.id):
            await call.answer("Доступ ограничен.", show_alert=True)
            return
        
        from bot import AdminStates
        await AdminStates.waiting_promo.set()
        await state.update_data(menu_chat_id=call.message.chat.id, menu_msg_id=call.message.message_id)
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Назад", callback_data=ADMIN_PROMOS))
        text = "Введи промокод в формате: КОД ДНЕЙ ЛИМИТ\nПример: FREE 3 50  (3 дня, до 50 активаций)"
        await edit_menu_text(call, text, kb)

    async def handle_promo_create(self, message: types.Message, state: FSMContext):
        """Создать промокод."""
        if not self.is_admin(message.from_user.id):
            await state.finish()
            return
        
        chat_id, msg_id = await self.get_menu_data(state, message=message)
        await self.delete_user_message(message)
        
        parts = (message.text or "").split()
        if len(parts) != 3:
            await self.safe_edit_message(chat_id, msg_id, "Неверный формат. Пример: FREE 3 50", 
                                       reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Назад", callback_data=ADMIN_PROMOS)), 
                                       parse_mode="Markdown")
            return
        
        code, days_str, limit_str = parts
        try:
            days_val = int(days_str)
            limit_val = int(limit_str)
        except Exception:
            days_val = 0
            limit_val = 0
        
        if days_val <= 0 or limit_val <= 0:
            await self.safe_edit_message(chat_id, msg_id, "Неверные числа. Пример: FREE 3 50", 
                                       reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Назад", callback_data=ADMIN_PROMOS)), 
                                       parse_mode="Markdown")
            return
        
        ok = add_promo(code, days=days_val, max_uses=limit_val)
        await state.finish()
        await self.safe_edit_message(chat_id, msg_id, "Промокод создан." if ok else "Такой код уже существует.", 
                                   reply_markup=admin_kb(), parse_mode="Markdown")

    async def handle_search_start(self, call: types.CallbackQuery, state: FSMContext):
        """Начать поиск пользователя."""
        if not self.is_admin(call.from_user.id):
            await call.answer("Доступ ограничен.", show_alert=True)
            return

        from bot import AdminStates
        await AdminStates.waiting_search_tg.set()
        await state.update_data(menu_chat_id=call.message.chat.id, menu_msg_id=call.message.message_id)
        
        from callbacks import ADMIN
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Назад", callback_data=ADMIN))
        from ui import edit_menu_text_pm
        await edit_menu_text_pm(call, "Введи Telegram ID пользователя", kb, parse_mode="HTML")

    async def handle_search_process(self, message: types.Message, state: FSMContext):
        """Обработать поиск пользователя - построено с нуля как рассылка."""
        if not self.is_admin(message.from_user.id):
            await state.finish()
            return
        
        chat_id, msg_id = await self.get_menu_data(state, message=message)
        await self.delete_user_message(message)
        
        tg_str = (message.text or "").strip()
        try:
            tg_req = int(tg_str)
        except Exception:
            tg_req = None
        
        if tg_req is None:
            # Неверный ввод - не сбрасываем состояние, просим повторить
            kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Назад", callback_data="admin"))
            await self.safe_edit_message(chat_id, msg_id, "Неверный ID. Введи число ещё раз", 
                                       reply_markup=kb, parse_mode="Markdown")
            return
        
        user = get_user_by_tg(tg_req)
        if not user:
            # Пользователь не найден - не сбрасываем состояние, просим повторить
            kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Назад", callback_data="admin"))
            await self.safe_edit_message(chat_id, msg_id, "Пользователь не найден. Попробуй ещё раз", 
                                       reply_markup=kb, parse_mode="Markdown")
            return
        
        # Успешный поиск - сбрасываем состояние и показываем результат
        await state.finish()
        
        # Создаем админ-клавиатуру
        kb_admin = InlineKeyboardMarkup(row_width=1)
        kb_admin.add(InlineKeyboardButton("📣 Рассылка", callback_data="admin_broadcast"))
        kb_admin.add(InlineKeyboardButton("🔎 Поиск по tg_id", callback_data="admin_search"))
        kb_admin.add(InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"))
        kb_admin.add(InlineKeyboardButton("🎟️ Промокоды", callback_data="admin_promos"))
        kb_admin.add(InlineKeyboardButton("⬅️ Назад", callback_data="back_main"))
        
        # Формируем текст профиля
        text = (
            "Пользователь:\n"
            f"- tg_id: <code>{html.escape(str(user.get('tg_id')))}</code>\n"
            f"- username: <code>@{html.escape(str(user.get('username') or '-'))}</code>\n"
            f"- first_name: <code>{html.escape(str(user.get('first_name') or '-'))}</code>\n"
            f"- last_name: <code>{html.escape(str(user.get('last_name') or '-'))}</code>\n"
            f"- зарегистрирован: <code>{html.escape(str(user.get('date_registered') or '-'))}</code>\n"
            f"- vpn_email: <code>{html.escape(str(user.get('vpn_email') or '-'))}</code>\n"
            f"- last_action: <code>{html.escape(str(user.get('last_action') or '-'))}</code>\n"
        )
        await self.safe_edit_message(chat_id, msg_id, text, reply_markup=kb_admin, parse_mode="HTML")

    async def handle_stats(self, call: types.CallbackQuery, state: FSMContext):
        """Показать статистику."""
        if not self.is_admin(call.from_user.id):
            await call.answer("Доступ ограничен.", show_alert=True)
            return
        
        await state.finish()
        total = count_users()
        with_vpn = count_users_with_vpn()
        promos = count_promos()
        uses = sum_promo_uses()
        
        # Дополнительная статистика
        from datetime import datetime
        from db import get_connection
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Пользователи за последние 7 дней
            cursor.execute("""
                SELECT COUNT(*) FROM users 
                WHERE date_registered >= date('now', '-7 days')
            """)
            new_users_week = cursor.fetchone()[0]
            
            # Пользователи за последние 30 дней
            cursor.execute("""
                SELECT COUNT(*) FROM users 
                WHERE date_registered >= date('now', '-30 days')
            """)
            new_users_month = cursor.fetchone()[0]
            
            # Активные промокоды
            cursor.execute("""
                SELECT COUNT(*) FROM promos 
                WHERE used_count < max_uses
            """)
            active_promos = cursor.fetchone()[0]
            
            # Конверсия в VPN пользователей
            conversion_rate = (with_vpn / total * 100) if total > 0 else 0
        
        text = (
            f"Статистика системы:\n\n"
            f"Пользователи:\n"
            f"• Всего: {total}\n"
            f"• С подпиской: {with_vpn} ({conversion_rate:.1f}%)\n"
            f"• За неделю: +{new_users_week}\n"
            f"• За месяц: +{new_users_month}\n\n"
            f"Промокоды:\n"
            f"• Создано: {promos}\n"
            f"• Активных: {active_promos}\n"
            f"• Активаций: {uses}\n\n"
            f"Конверсия: {conversion_rate:.1f}%"
        )
        
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="admin"))
        await edit_menu_text(call, text, kb)

    async def handle_sync(self, call: types.CallbackQuery, state: FSMContext):
        """Синхронизировать БД с XUI панелью."""
        if not self.is_admin(call.from_user.id):
            await call.answer("Доступ ограничен.", show_alert=True)
            return
        
        await state.finish()
        session = get_session_cached()
        if not session:
            await call.answer("XUI недоступен.", show_alert=True)
            return
        
        await call.answer("Синхронизация...", show_alert=True)
        
        try:
            stats = sync_users_with_xui(session)
            if "error" in stats:
                text = f"Ошибка синхронизации: {stats['error']}"
            else:
                text = (
                    f"🔄 Синхронизация завершена:\n\n"
                    f"• Пользователей в БД: {stats['users_in_db']}\n"
                    f"• Пользователей в XUI: {stats['users_in_xui']}\n"
                    f"• Синхронизировано: {stats['synced']}\n"
                    f"• Очищено: {stats['cleared']}\n"
                    f"• Ошибок: {stats['errors']}"
                )
            
            await edit_menu_text(call, text, admin_kb())
            
        except Exception as e:
            logging.error(f"Ошибка синхронизации: {e}")
            await edit_menu_text(call, f"Ошибка синхронизации: {str(e)}", admin_kb())

    async def handle_dismiss(self, call: types.CallbackQuery):
        """Удалить сообщение рассылки."""
        try:
            await self.bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        await call.answer()

    async def handle_admin_logs(self, call: types.CallbackQuery, state: FSMContext):
        """Показать последние строки логов."""
        if not self.is_admin(call.from_user.id):
            await call.answer("Доступ ограничен.", show_alert=True)
            return
        await state.finish()
        try:
            base_dir = "/app/logs"
            bot_path = os.path.join(base_dir, 'bot.log')
            pay_path = os.path.join(base_dir, 'payments.log')
            # ensure files exist
            os.makedirs(base_dir, exist_ok=True)
            for p in (bot_path, pay_path):
                try:
                    if not os.path.exists(p):
                        open(p, 'a', encoding='utf-8').close()
                except Exception:
                    pass

            def tail(path: str, lines: int = 50) -> str:
                try:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        data = f.readlines()
                        return ''.join(data[-lines:]) if data else '(пусто)'
                except FileNotFoundError:
                    return '(файл не найден)'
                except Exception as e:
                    return f'(ошибка чтения: {e})'

            bot_log_raw = tail(bot_path, 50)
            pay_log_raw = tail(pay_path, 50)

            # Prepare safe HTML with hard caps
            def safe_clip(s: str, cap: int = 1800) -> str:
                from html import escape
                s = escape(s)
                if len(s) > cap:
                    return s[-cap:]
                return s

            bot_clip = safe_clip(bot_log_raw, 1800)
            pay_clip = safe_clip(pay_log_raw, 1800)

            text = (
                "Последние логи:\n\n"
                "🧾 bot.log (50 строк):\n"
                f"<pre><code>{bot_clip}</code></pre>\n\n"
                "💳 payments.log (50 строк):\n"
                f"<pre><code>{pay_clip}</code></pre>"
            )

            # If still too long for Telegram, fallback to sending documents
            if len(text) > 3800:
                kb = InlineKeyboardMarkup(row_width=1)
                kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="admin"))
                await edit_menu_text_pm(call, "Логи большие — отправляю файлами ниже.", kb, parse_mode="HTML")
                try:
                    from aiogram.types import InputFile
                    await self.bot.send_document(call.message.chat.id, InputFile(bot_path), caption="bot.log (последний файл)")
                except Exception:
                    pass
                try:
                    from aiogram.types import InputFile
                    await self.bot.send_document(call.message.chat.id, InputFile(pay_path), caption="payments.log (последний файл)")
                except Exception:
                    pass
                return

            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="admin"))
            await edit_menu_text_pm(call, text, kb, parse_mode="HTML")
        except Exception as e:
            logging.error(f"admin_logs_error: {e}")
            await call.answer("Не удалось показать логи.", show_alert=True)
