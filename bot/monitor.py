"""
Anomaly monitoring: ОТКЛЮЧЕН - работает только через cron скрипт.
Мониторинг метрик вынесен в отдельный процесс для снижения нагрузки на бота.
"""

from typing import Dict, List
import time
import logging

from .config import ADMIN_IDS


class AnomalyMonitor:
    """
    AnomalyMonitor ОТКЛЮЧЕН в основном боте.
    
    Мониторинг метрик работает через:
    - utils/anomaly_check.py (запускается cron каждые 5 минут)
    - utils/monitor.sh (системный мониторинг)
    
    Это снижает нагрузку на основной бот и улучшает производительность.
    """
    
    def __init__(self, bot, notify_admins: List[int] = None):
        self.bot = bot
        self.notify_admins = notify_admins or ADMIN_IDS
        self.last_alert_ts: Dict[str, float] = {}
        logging.info("AnomalyMonitor initialized (monitoring disabled in main bot)")

    async def notify(self, text: str):
        """Отправка уведомлений админам."""
        for admin_id in self.notify_admins:
            try:
                await self.bot.send_message(admin_id, text)
            except Exception:
                pass

    # IP мониторинг полностью удален

    async def check_traffic_spike(self, client_email: str, threshold_gb: float = 30.0):
        """Мониторинг трафика отключен в основном боте."""
        logging.debug(f"Traffic monitoring disabled in main bot for {client_email}")
        return

    async def check_anomalies(self, client_email: str):
        """Мониторинг аномалий отключен в основном боте."""
        logging.debug(f"Anomaly monitoring disabled in main bot for {client_email}")
        return


