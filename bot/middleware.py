"""
Middleware для логирования, обработки ошибок и мониторинга.
Улучшает масштабируемость и отладку.
"""

import logging
import time
from typing import Callable, Dict, Any
from aiogram import types
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.dispatcher import FSMContext

# Настройка логирования
import os
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseMiddleware):
    """Middleware для логирования всех действий пользователей."""
    
    async def on_process_message(self, message: types.Message, data: dict):
        """Логировать входящие сообщения."""
        user = message.from_user
        logger.info(f"Message from {user.id} (@{user.username}): {message.text[:100] if message.text else 'Non-text'}")
    
    async def on_process_callback_query(self, call: types.CallbackQuery, data: dict):
        """Логировать callback запросы."""
        user = call.from_user
        logger.info(f"Callback from {user.id} (@{user.username}): {call.data}")
    
    async def on_post_process_message(self, message: types.Message, data: dict, response: Any):
        """Логировать ответы на сообщения."""
        if response:
            logger.info(f"Response sent to {message.from_user.id}")


class ErrorHandlingMiddleware(BaseMiddleware):
    """Middleware для централизованной обработки ошибок."""
    
    async def on_process_error(self, update: types.Update, error: Exception):
        """Обработать ошибки."""
        logger.error(f"Error in update {update}: {error}", exc_info=True)
        
        # Попытка отправить пользователю понятное сообщение
        if update.message:
            try:
                await update.message.answer("Произошла ошибка. Попробуй позже, браток.")
            except Exception:
                pass
        elif update.callback_query:
            try:
                await update.callback_query.answer("Ошибка. Попробуй снова.", show_alert=True)
            except Exception:
                pass
        
        return True


class PerformanceMiddleware(BaseMiddleware):
    """Middleware для мониторинга производительности."""
    
    def __init__(self):
        self.request_times = {}
        super().__init__()
    
    async def on_process_message(self, message: types.Message, data: dict):
        """Засечь время начала обработки."""
        self.request_times[message.message_id] = time.time()
    
    async def on_process_callback_query(self, call: types.CallbackQuery, data: dict):
        """Засечь время начала обработки callback."""
        self.request_times[f"cb_{call.id}"] = time.time()
    
    async def on_post_process_message(self, message: types.Message, data: dict, response: Any):
        """Измерить время обработки сообщения."""
        start_time = self.request_times.pop(message.message_id, None)
        if start_time:
            duration = time.time() - start_time
            if duration > 1.0:  # Логировать медленные запросы
                logger.warning(f"Slow message processing: {duration:.2f}s for user {message.from_user.id}")
    
    async def on_post_process_callback_query(self, call: types.CallbackQuery, data: dict, response: Any):
        """Измерить время обработки callback."""
        start_time = self.request_times.pop(f"cb_{call.id}", None)
        if start_time:
            duration = time.time() - start_time
            if duration > 0.5:  # Логировать медленные callback
                logger.warning(f"Slow callback processing: {duration:.2f}s for user {call.from_user.id}")


class RateLimitMiddleware(BaseMiddleware):
    """Middleware для ограничения частоты запросов."""
    
    def __init__(self, max_actions: int = 3, window_sec: int = 3):
        self.max_actions = max_actions
        self.window_sec = window_sec
        self.user_requests = {}
        super().__init__()
    
    async def on_process_message(self, message: types.Message, data: dict):
        """Проверить лимит запросов для пользователя."""
        user_id = message.from_user.id
        now = time.time()
        
        # Очистить старые записи (старше окна)
        if user_id in self.user_requests:
            self.user_requests[user_id] = [
                req_time for req_time in self.user_requests[user_id] 
                if now - req_time < self.window_sec
            ]
        else:
            self.user_requests[user_id] = []
        
        # Проверить лимит
        if len(self.user_requests[user_id]) >= self.max_actions:
            logger.warning(f"Rate limit exceeded for user {user_id}")
            await message.answer("Слишком много запросов. Подожди немного.")
            return False
        
        # Добавить текущий запрос
        self.user_requests[user_id].append(now)
        return True
    
    async def on_process_callback_query(self, call: types.CallbackQuery, data: dict):
        """Проверить лимит для callback."""
        user_id = call.from_user.id
        now = time.time()
        
        if user_id in self.user_requests:
            self.user_requests[user_id] = [
                req_time for req_time in self.user_requests[user_id] 
                if now - req_time < self.window_sec
            ]
        else:
            self.user_requests[user_id] = []
        
        if len(self.user_requests[user_id]) >= self.max_actions:
            await call.answer("Слишком много запросов. Подожди немного.", show_alert=True)
            return False
        
        self.user_requests[user_id].append(now)
        return True


class AdminOnlyMiddleware(BaseMiddleware):
    """Middleware для проверки прав администратора."""
    
    def __init__(self, admin_ids: list):
        self.admin_ids = admin_ids
        super().__init__()
    
    async def on_process_callback_query(self, call: types.CallbackQuery, data: dict):
        """Проверить права админа для callback."""
        if call.data.startswith("admin") and call.from_user.id not in self.admin_ids:
            await call.answer("Не по рангу, браток.", show_alert=True)
            return False
        return True


class DatabaseMiddleware(BaseMiddleware):
    """Middleware для управления соединениями с БД."""
    
    def __init__(self, admin_ids: list):
        self.admin_ids = admin_ids
        super().__init__()
    
    async def on_process_message(self, message: types.Message, data: dict):
        """Подготовить данные для обработчика."""
        data['user_id'] = message.from_user.id
        data['username'] = message.from_user.username
        data['is_admin'] = message.from_user.id in self.admin_ids
    
    async def on_process_callback_query(self, call: types.CallbackQuery, data: dict):
        """Подготовить данные для callback."""
        data['user_id'] = call.from_user.id
        data['username'] = call.from_user.username
        data['is_admin'] = call.from_user.id in self.admin_ids


def setup_middleware(dp, admin_ids: list):
    """Настроить все middleware для диспетчера."""
    
    # Добавить middleware в правильном порядке
    dp.middleware.setup(LoggingMiddleware())
    dp.middleware.setup(ErrorHandlingMiddleware())
    dp.middleware.setup(PerformanceMiddleware())
    from config import RATE_MAX_ACTIONS, RATE_WINDOW_SEC
    dp.middleware.setup(RateLimitMiddleware(max_actions=RATE_MAX_ACTIONS, window_sec=RATE_WINDOW_SEC))
    dp.middleware.setup(AdminOnlyMiddleware(admin_ids))
    dp.middleware.setup(DatabaseMiddleware(admin_ids))
    
    logger.info("All middleware configured successfully")
