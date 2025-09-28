#!/usr/bin/env python3
"""
Скрипт для мониторинга трафика VPN пользователей.
Запускается из cron 1 раз в день вместе с бэкапом БД.

Мониторинг только трафика - IP мониторинг удален (X-UI не поддерживает).
"""

import sys
import os
import asyncio
import logging
from datetime import datetime

# Добавляем путь к модулям бота
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.metrics import XUIMetricsCollector
from bot.db import list_users_with_vpn
from bot.api import get_session_cached

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TelegramNotifier:
    """Отправка уведомлений через Telegram API"""
    
    def __init__(self, bot_token: str, admin_ids: list):
        self.bot_token = bot_token
        self.admin_ids = admin_ids
    
    async def send_message(self, chat_id: int, text: str):
        """Отправка уведомления админу через Telegram API"""
        import requests
        
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML'
        }
        
        try:
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                logger.info(f"Notification sent to admin {chat_id}")
            else:
                logger.error(f"Failed to send notification: {response.status_code}")
        except Exception as e:
            logger.error(f"Error sending notification: {e}")

async def check_traffic_anomalies():
    """Проверка аномалий трафика для всех пользователей"""
    logger.info("Starting daily traffic monitoring...")
    
    try:
        # Получаем настройки из .env
        from dotenv import load_dotenv
        load_dotenv()
        
        bot_token = os.getenv('BOT_TOKEN')
        admin_ids_str = os.getenv('ADMIN_IDS', '')
        admin_ids = [int(x.strip()) for x in admin_ids_str.split(',') if x.strip()]
        
        if not bot_token or not admin_ids:
            logger.error("BOT_TOKEN or ADMIN_IDS not configured")
            return
        
        # Создаем уведомитель
        notifier = TelegramNotifier(bot_token, admin_ids)
        
        # Получаем сессию X-UI
        session = get_session_cached()
        if not session:
            logger.error("Failed to get X-UI session")
            return
        
        # Получаем всех пользователей с VPN
        users = list_users_with_vpn()
        logger.info(f"Checking traffic for {len(users)} users")
        
        # Создаем сборщик метрик
        collector = XUIMetricsCollector()
        
        # Проверяем каждого пользователя
        high_traffic_users = []
        
        for user in users:
            email = user.get('vpn_email')
            tg_id = user.get('tg_id')
            
            if not email:
                continue
            
            try:
                # Получаем статистику трафика
                traffic_data = collector.get_client_traffic(email, 24)  # За 24 часа
                total_gb = traffic_data.get('total', 0)
                
                # Порог: 50 ГБ за день
                if total_gb >= 50.0:
                    high_traffic_users.append({
                        'email': email,
                        'tg_id': tg_id,
                        'traffic_gb': total_gb,
                        'upload_gb': traffic_data.get('upload', 0),
                        'download_gb': traffic_data.get('download', 0)
                    })
                    
                logger.info(f"User {email}: {total_gb:.1f} GB in 24h")
                
            except Exception as e:
                logger.error(f"Error checking traffic for {email}: {e}")
        
        # Отправляем уведомления админам
        if high_traffic_users:
            message = "📊 <b>ЕЖЕДНЕВНЫЙ ОТЧЕТ ПО ТРАФИКУ</b>\n\n"
            message += f"Пользователей с высоким трафиком: {len(high_traffic_users)}\n\n"
            
            for user in high_traffic_users[:10]:  # Показываем только первых 10
                message += f"• {user['email']}: {user['traffic_gb']:.1f} ГБ\n"
                message += f"  ↑ {user['upload_gb']:.1f} ГБ | ↓ {user['download_gb']:.1f} ГБ\n"
            
            if len(high_traffic_users) > 10:
                message += f"\n... и еще {len(high_traffic_users) - 10} пользователей"
            
            # Отправляем всем админам
            for admin_id in admin_ids:
                await notifier.send_message(admin_id, message)
        else:
            logger.info("No high traffic users found")
        
        logger.info("Daily traffic monitoring completed successfully")
        
    except Exception as e:
        logger.error(f"Traffic monitoring failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(check_traffic_anomalies())
