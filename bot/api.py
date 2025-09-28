import requests
import uuid
import json
import logging
from datetime import datetime
from dateutil.relativedelta import relativedelta
from config import XUI_URL, XUI_USER, XUI_PASSWORD, XUI_HOST, XUI_USERNAME, XUI_PASSWORD, SERVER_HOST, SERVER_PORT, REALITY_PBK, REALITY_SID, REALITY_SNI, REALITY_FP, XUI_LOGIN_RETRIES, XUI_LOGIN_TIMEOUT, XUI_LOGIN_COOLDOWN_SEC, CLIENT_INFO_TTL_SEC
import random
import time
import os

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

# Simple in-process session cache
_SESSION_CACHE = {
    "session": None,
    "ts": 0.0,
}

# Client info cache to reduce XUI calls
_CLIENT_CACHE = {}
_LAST_FAIL_TS = 0.0


def get_session_cached(max_age_sec: int = 300):
    """Возвращает кэшированную сессию XUI, обновляет раз в max_age_sec сек или при неуспехе."""
    global _LAST_FAIL_TS
    now = time.time()
    
    # Если недавно была ошибка входа, ждем cooldown
    if (now - _LAST_FAIL_TS) < XUI_LOGIN_COOLDOWN_SEC:
        logging.debug("XUI login cooldown active, skipping login attempt")
        return None
    
    sess = _SESSION_CACHE.get("session")
    ts = _SESSION_CACHE.get("ts", 0.0)
    if sess is not None and (now - ts) < max_age_sec:
        return sess
    sess = get_token()
    if sess is not None:
        _SESSION_CACHE["session"] = sess
        _SESSION_CACHE["ts"] = now
        _LAST_FAIL_TS = 0.0  # Сброс cooldown при успехе
    else:
        _LAST_FAIL_TS = now  # Установка cooldown при неудаче
    return sess

def get_token():
    """Авторизация в XUI. Возвращает requests.Session или None."""
    url = f"{XUI_URL}/login"
    data = {"username": XUI_USER, "password": XUI_PASSWORD}
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    
    # Retry logic with exponential backoff
    for attempt in range(XUI_LOGIN_RETRIES):
        try:
            response = session.post(url, json=data, timeout=XUI_LOGIN_TIMEOUT)
            response.raise_for_status()
            if response.json().get("success"):
                logging.info("Вход в XUI выполнен успешно")
                return session
            else:
                logging.error(f"Ошибка входа: {response.json()}")
                return None
        except requests.RequestException as e:
            logging.error(f"Ошибка при входе (попытка {attempt + 1}): {e}")
            if attempt < XUI_LOGIN_RETRIES - 1:
                delay = 0.5 * (2 ** attempt)  # Exponential backoff: 0.5s, 1s, 2s
                time.sleep(delay)
            else:
                return None
    return None

def add_client(session, telegram_id, months):
    """Создать клиента с email=telegram_id на указанный срок (месяцы). Возвращает client_id и результат."""
    if months is None:
        raise ValueError("Необходимо указать срок действия (months)")
    url = f"{XUI_URL}/panel/api/inbounds/addClient"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    client_id = str(uuid.uuid4())
    now = datetime.now()
    expiry_dt = int((now + relativedelta(months=months)).timestamp() * 1000)
    email = str(telegram_id)
    if check_if_client_exists(session, telegram_id):
        logging.warning(f"Клиент с email={email} уже существует. Пропускаем создание.")
        return {"error": "Client already exists", "client_id": None}
    settings = {
        "clients": [{
            "id": client_id,
            "flow": "xtls-rprx-vision",
            "email": email,
            "limitIp": 1,
            "totalGB": 0,
            "expiryTime": expiry_dt,
            "enable": True,
            "tgId": str(telegram_id),
            "subId": email,
            "reset": 0
        }]
    }
    data = {
        "id": 1,
        "settings": json.dumps(settings)
    }
    try:
        response = session.post(url, json=data, headers=headers, timeout=5)
        response.raise_for_status()
        logging.info(f"Клиент {email} успешно добавлен.")
        return {"client_id": client_id, "result": response.json()}
    except requests.RequestException as e:
        logging.error(f"Ошибка при добавлении клиента: {e}")
        return {"error": str(e), "client_id": None}

def add_client_days(session, telegram_id, days):
    """Создать клиента на указанное число дней (days). Возвращает client_id и результат."""
    if days is None or int(days) <= 0:
        raise ValueError("Необходимо указать положительное число дней")
    url = f"{XUI_URL}/panel/api/inbounds/addClient"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    client_id = str(uuid.uuid4())
    now = datetime.now()
    expiry_dt = int((now + relativedelta(days=days)).timestamp() * 1000)
    email = str(telegram_id)
    if check_if_client_exists(session, telegram_id):
        logging.warning(f"Клиент с email={email} уже существует. Пропускаем создание.")
        return {"error": "Client already exists", "client_id": None}
    settings = {
        "clients": [{
            "id": client_id,
            "flow": "xtls-rprx-vision",
            "email": email,
            "limitIp": 1,
            "totalGB": 0,
            "expiryTime": expiry_dt,
            "enable": True,
            "tgId": str(telegram_id),
            "subId": email,
            "reset": 0
        }]
    }
    data = {
        "id": 1,
        "settings": json.dumps(settings)
    }
    try:
        response = session.post(url, json=data, headers=headers, timeout=5)
        response.raise_for_status()
        logging.info(f"Клиент {email} успешно добавлен на {days} дн.")
        return {"client_id": client_id, "result": response.json()}
    except requests.RequestException as e:
        logging.error(f"Ошибка при добавлении клиента: {e}")
        return {"error": str(e), "client_id": None}

def check_if_client_exists(session, telegram_id):
    """Проверить, есть ли клиент с таким email (telegram_id)."""
    url = f"{XUI_URL}/panel/api/inbounds/list"
    headers = {"Accept": "application/json"}
    email = str(telegram_id)
    try:
        response = session.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        inbounds = response.json().get('obj', [])
        for inbound in inbounds:
            settings = inbound.get('settings', {})
            if isinstance(settings, str):
                settings = json.loads(settings)
            clients = settings.get("clients", [])
            for client in clients:
                if client.get('email') == email:
                    return True
        return False
    except requests.RequestException as e:
        logging.error(f"Ошибка при проверке существования клиента: {e}")
        return False

def get_client_info(session, telegram_id):
    """
    Получить inbound_id и client по email (telegram_id).
    """
    import json
    import logging
    url = f"{XUI_URL}/panel/api/inbounds/list"
    headers = {"Accept": "application/json"}
    email = str(telegram_id)
    # serve from cache if fresh
    now_ts = time.time()
    cached = _CLIENT_CACHE.get(email)
    if cached and (now_ts - cached.get("ts", 0)) < CLIENT_INFO_TTL_SEC:
        return cached.get("inbound"), cached.get("client")
    response = session.get(url, headers=headers, timeout=5)
    response.raise_for_status()
    inbounds = response.json().get('obj', [])
    for inbound in inbounds:
        inbound_id = inbound.get('id')
        settings = inbound.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        clients = settings.get("clients", [])
        for client in clients:
            if client.get('email') == email:
                logging.debug("Inbound fetched for email=%s (cached)", email)
                _CLIENT_CACHE[email] = {"inbound": inbound, "client": client, "ts": now_ts}
                return inbound, client
    return None, None

def invalidate_client_cache(email: str):
    try:
        _CLIENT_CACHE.pop(str(email), None)
    except Exception:
        pass

def generate_vless_link(inbound: dict, client: dict) -> str:
    """Собирает VLESS Reality ссылку по данным inbound и client (как в панели)."""
    import json
    port = inbound.get('port') or SERVER_PORT
    host = inbound.get('listen') or inbound.get('remark') or SERVER_HOST
    if not host or host == "vles":
        host = SERVER_HOST
    email = client.get('email')
    uuid = client.get('id')
    flow = client.get('flow', '')
    stream_settings = inbound.get('streamSettings')
    if isinstance(stream_settings, str):
        stream_settings = json.loads(stream_settings)
    security = stream_settings.get('security', 'reality')
    network = stream_settings.get('network', 'tcp')
    reality_settings = stream_settings.get('realitySettings', {})
    if isinstance(reality_settings, str):
        reality_settings = json.loads(reality_settings)
    public_key = reality_settings.get('publicKey', '') or REALITY_PBK
    short_ids = reality_settings.get('shortIds', [])
    short_id = short_ids[0] if short_ids else REALITY_SID
    server_names = reality_settings.get('serverNames', [])
    sni = server_names[0] if server_names else REALITY_SNI
    fp = REALITY_FP
    return (
        f"vless://{uuid}@{host}:{port}?type={network}&security={security}"
        f"&pbk={public_key}&fp={fp}&sni={sni}&sid={short_id}&spx=%2F&flow={flow}#vles-{email}"
    )

def remove_client(session, telegram_id):
    """
    Удалить клиента по email (telegram_id) из всех inbounds.
    """
    import json
    import logging

    url = f"{XUI_URL}/panel/api/inbounds/list"
    headers = {"Accept": "application/json"}
    email = str(telegram_id)
    try:
        response = session.get(url, headers=headers)
        response.raise_for_status()
        inbounds = response.json().get('obj', [])
        for inbound in inbounds:
            inbound_id = inbound.get('id')
            settings = inbound.get('settings', {})
            if isinstance(settings, str):
                settings = json.loads(settings)
            clients = settings.get("clients", [])
            for client in clients:
                if client.get('email') == email:
                    client_id = client.get('id')
                    del_url = f"{XUI_URL}/panel/api/inbounds/{inbound_id}/delClient/{client_id}"
                    del_resp = session.post(del_url, headers=headers)
                    print("Ответ XUI:", del_resp.text)
                    del_resp.raise_for_status()
                    logging.info(f"Клиент {email} удалён.")
                    return True
        logging.warning(f"Клиент {email} не найден для удаления.")
        return False
    except requests.RequestException as e:
        logging.error(f"Ошибка при удалении клиента: {e}")
        return False
    
def extend_client(session, telegram_id, months):
    """
    Продлить срок действия клиента по email (telegram_id) на months месяцев.
    """
    from datetime import datetime
    from dateutil.relativedelta import relativedelta
    import json
    import logging

    url = f"{XUI_URL}/panel/api/inbounds/list"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    email = str(telegram_id)
    try:
        response = session.get(url, headers=headers)
        response.raise_for_status()
        inbounds = response.json().get('obj', [])
        for inbound in inbounds:
            settings = inbound.get('settings', {})
            inbound_id = inbound.get('id')  # это ЧИСЛО!
            if isinstance(settings, str):
                settings = json.loads(settings)
            clients = settings.get("clients", [])
            for client in clients:
                if client.get('email') == email:
                    client_id = client.get('id')
                    now = datetime.now()
                    new_expiry = int((now + relativedelta(months=months)).timestamp() * 1000)
                    updated_client = client.copy()
                    updated_client['expiryTime'] = new_expiry
                    # enforce single concurrent IP
                    try:
                        if int(updated_client.get('limitIp', 0)) < 1:
                            updated_client['limitIp'] = 1
                    except Exception:
                        updated_client['limitIp'] = 1
                    # Формируем settings только с этим клиентом!
                    settings_obj = {"clients": [updated_client]}
                    data = {
                        "id": inbound_id,  # Числовой id inbound-а!
                        "settings": json.dumps(settings_obj)
                    }
                    upd_url = f"{XUI_URL}/panel/api/inbounds/updateClient/{client_id}"
                    upd_resp = session.post(upd_url, json=data, headers=headers)
                    print("Ответ XUI:", upd_resp.text)
                    upd_resp.raise_for_status()
                    logging.info(f"Клиент {email} продлён до {new_expiry}.")
                    invalidate_client_cache(email)
                    return True
        logging.warning(f"Клиент {email} не найден для продления.")
        return False
    except requests.RequestException as e:
        logging.error(f"Ошибка при продлении клиента: {e}")
    return False

def extend_client_days(session, telegram_id, days: int) -> bool:
    """Продлить срок действия клиента на указанное число дней. Не создаёт нового клиента.
    Логика: найти inbound+client по email (telegram_id), взять max(now, currentExpiry) + days.
    """
    if days is None or int(days) <= 0:
        return False
    url_list = f"{XUI_URL}/panel/api/inbounds/list"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    email = str(telegram_id)
    try:
        response = session.get(url_list, headers=headers)
        response.raise_for_status()
        inbounds = response.json().get('obj', [])
        for inbound in inbounds:
            settings = inbound.get('settings', {})
            inbound_id = inbound.get('id')
            if isinstance(settings, str):
                settings = json.loads(settings)
            clients = settings.get("clients", [])
            for client in clients:
                if client.get('email') == email:
                    client_id = client.get('id')
                    now_ms = int(datetime.now().timestamp() * 1000)
                    current_exp = int(client.get('expiryTime') or 0)
                    base = current_exp if current_exp > now_ms else now_ms
                    new_expiry = base + int(days) * 24 * 60 * 60 * 1000
                    updated_client = client.copy()
                    updated_client['expiryTime'] = new_expiry
                    # enforce single concurrent IP
                    try:
                        if int(updated_client.get('limitIp', 0)) < 1:
                            updated_client['limitIp'] = 1
                    except Exception:
                        updated_client['limitIp'] = 1
                    settings_obj = {"clients": [updated_client]}
                    upd_url = f"{XUI_URL}/panel/api/inbounds/updateClient/{client_id}"
                    data = {"id": inbound_id, "settings": json.dumps(settings_obj)}
                    upd_resp = session.post(upd_url, json=data, headers=headers)
                    logging.info("Ответ XUI: %s", getattr(upd_resp, 'text', ''))
                    upd_resp.raise_for_status()
                    logging.info(f"Клиент {email} продлён на {days} дн. До {new_expiry}.")
                    invalidate_client_cache(email)
                    return True
        logging.warning(f"Клиент {email} не найден для продления дней.")
        return False
    except requests.RequestException as e:
        logging.error(f"Ошибка при продлении клиента на дни: {e}")
    return False