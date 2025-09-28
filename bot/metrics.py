"""
Модуль для сбора реальных метрик X-UI панели.
Получает статистику по трафику и IP адресам клиентов.
"""

import requests
import json
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import time

from config import XUI_URL, XUI_USER, XUI_PASSWORD

logger = logging.getLogger(__name__)


class XUIMetricsCollector:
    """Сборщик метрик из X-UI панели."""
    
    def __init__(self):
        self.session = None
        self._last_login = 0
        self._login_interval = 300  # 5 минут
    
    def _get_session(self):
        """Получить активную сессию X-UI."""
        now = time.time()
        if not self.session or (now - self._last_login) > self._login_interval:
            try:
                self.session = requests.Session()
                login_data = {"username": XUI_USER, "password": XUI_PASSWORD}
                response = self.session.post(f"{XUI_URL}/login", json=login_data, timeout=10)
                
                if response.json().get("success"):
                    self._last_login = now
                    logger.info("X-UI session renewed for metrics collection")
                else:
                    logger.error("Failed to login to X-UI for metrics")
                    self.session = None
            except Exception as e:
                logger.error(f"Error logging into X-UI: {e}")
                self.session = None
        
        return self.session
    
    def get_client_stats(self, client_email: str) -> Dict:
        """Получить статистику клиента по email."""
        session = self._get_session()
        if not session:
            return {}
        
        try:
            # Получаем список всех inbounds
            response = session.get(f"{XUI_URL}/panel/api/inbounds/list", timeout=10)
            inbounds = response.json().get('obj', [])
            
            for inbound in inbounds:
                settings = inbound.get('settings', {})
                if isinstance(settings, str):
                    settings = json.loads(settings)
                
                clients = settings.get("clients", [])
                for client in clients:
                    if client.get('email') == client_email:
                        # Получаем статистику клиента
                        inbound_id = inbound.get('id')
                        client_id = client.get('id')
                        
                        # ВАЖНО: Проверяем доступные API endpoints
                        # Попробуем разные варианты получения статистики
                        stats_data = {}
                        
                        # Вариант 1: clientTraffics endpoint
                        try:
                            stats_response = session.get(
                                f"{XUI_URL}/panel/api/inbounds/{inbound_id}/clientTraffics/{client_id}",
                                timeout=10
                            )
                            if stats_response.status_code == 200:
                                stats_data = stats_response.json().get('obj', {})
                                logger.info(f"Got stats from clientTraffics for {client_email}: {stats_data}")
                        except Exception as e:
                            logger.debug(f"clientTraffics endpoint failed for {client_email}: {e}")
                        
                        # Вариант 2: Если clientTraffics не работает, используем данные из клиента
                        if not stats_data:
                            # X-UI может хранить статистику прямо в объекте клиента
                            stats_data = {
                                'up': client.get('up', 0),
                                'down': client.get('down', 0),
                                'total': client.get('total', 0)
                            }
                            logger.info(f"Using client data for {client_email}: {stats_data}")
                        
                        # Вариант 3: Попробуем общий endpoint статистики
                        if not stats_data or (stats_data.get('up', 0) == 0 and stats_data.get('down', 0) == 0):
                            try:
                                stats_response = session.get(
                                    f"{XUI_URL}/panel/api/inbounds/{inbound_id}/clients/{client_id}/traffic",
                                    timeout=10
                                )
                                if stats_response.status_code == 200:
                                    stats_data = stats_response.json().get('obj', {})
                                    logger.info(f"Got stats from traffic endpoint for {client_email}: {stats_data}")
                            except Exception as e:
                                logger.debug(f"Traffic endpoint failed for {client_email}: {e}")
                        
                        return {
                            'client_id': client_id,
                            'email': client_email,
                            'stats': stats_data,
                            'inbound_id': inbound_id
                        }
            
            return {}
        except Exception as e:
            logger.error(f"Error getting client stats for {client_email}: {e}")
            return {}
    
    # IP мониторинг полностью удален - X-UI не поддерживает
    
    def get_client_traffic(self, client_email: str, hours: int = 6) -> Dict:
        """Получить статистику трафика клиента за последние N часов."""
        client_stats = self.get_client_stats(client_email)
        if not client_stats:
            logger.warning(f"No client stats found for {client_email}")
            return {'upload': 0, 'download': 0, 'total': 0}
        
        stats = client_stats.get('stats', {})
        logger.info(f"Raw stats for {client_email}: {stats}")
        
        # Пробуем разные варианты полей для трафика
        total_upload = 0
        total_download = 0
        
        # Вариант 1: up/down (стандартные поля)
        if 'up' in stats and 'down' in stats:
            total_upload = stats.get('up', 0)
            total_download = stats.get('down', 0)
            logger.info(f"Using up/down fields: upload={total_upload}, download={total_download}")
        
        # Вариант 2: upload/download
        elif 'upload' in stats and 'download' in stats:
            total_upload = stats.get('upload', 0)
            total_download = stats.get('download', 0)
            logger.info(f"Using upload/download fields: upload={total_upload}, download={total_download}")
        
        # Вариант 3: uplink/downlink
        elif 'uplink' in stats and 'downlink' in stats:
            total_upload = stats.get('uplink', 0)
            total_download = stats.get('downlink', 0)
            logger.info(f"Using uplink/downlink fields: upload={total_upload}, download={total_download}")
        
        # Вариант 4: tx/rx (transmit/receive)
        elif 'tx' in stats and 'rx' in stats:
            total_upload = stats.get('tx', 0)
            total_download = stats.get('rx', 0)
            logger.info(f"Using tx/rx fields: upload={total_upload}, download={total_download}")
        
        # Вариант 5: Если ничего не найдено, логируем все доступные поля
        else:
            logger.warning(f"No traffic fields found for {client_email}. Available fields: {list(stats.keys())}")
            # Попробуем взять любые числовые поля
            for key, value in stats.items():
                if isinstance(value, (int, float)) and value > 0:
                    logger.info(f"Found numeric field {key}: {value}")
        
        # Конвертируем в ГБ
        upload_gb = total_upload / (1024 ** 3)
        download_gb = total_download / (1024 ** 3)
        total_gb = upload_gb + download_gb
        
        result = {
            'upload': upload_gb,
            'download': download_gb,
            'total': total_gb,
            'upload_bytes': total_upload,
            'download_bytes': total_download
        }
        
        logger.info(f"Final traffic data for {client_email}: {result}")
        return result
    
    def get_all_clients_metrics(self) -> Dict[str, Dict]:
        """Получить метрики всех клиентов."""
        session = self._get_session()
        if not session:
            return {}
        
        try:
            response = session.get(f"{XUI_URL}/panel/api/inbounds/list", timeout=10)
            inbounds = response.json().get('obj', [])
            
            all_metrics = {}
            
            for inbound in inbounds:
                settings = inbound.get('settings', {})
                if isinstance(settings, str):
                    settings = json.loads(settings)
                
                clients = settings.get("clients", [])
                for client in clients:
                    email = client.get('email')
                    if email:
                        all_metrics[email] = {
                            'traffic': self.get_client_traffic(email),
                            'ips': self.get_client_ips(email),
                            'client_info': client
                        }
            
            return all_metrics
            
        except Exception as e:
            logger.error(f"Error getting all clients metrics: {e}")
            return {}


# Глобальный экземпляр сборщика метрик
metrics_collector = XUIMetricsCollector()


def get_client_metrics(client_email: str) -> Dict:
    """Получить метрики клиента (только трафик)."""
    return {
        'traffic_6h': metrics_collector.get_client_traffic(client_email, 6)
    }


def get_all_metrics() -> Dict[str, Dict]:
    """Получить метрики всех клиентов."""
    return metrics_collector.get_all_clients_metrics()
