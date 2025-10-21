import base64
import requests
import uuid
import json
import logging
from datetime import datetime
from typing import Optional
from dateutil.relativedelta import relativedelta
from config import XUI_URL, XUI_USER, XUI_PASSWORD, XUI_HOST, XUI_USERNAME, XUI_PASSWORD, SERVER_HOST, SERVER_PORT, REALITY_PBK, REALITY_SID, REALITY_SNI, REALITY_FP, XUI_LOGIN_RETRIES, XUI_LOGIN_TIMEOUT, XUI_LOGIN_COOLDOWN_SEC, CLIENT_INFO_TTL_SEC
from tariffs import get_service_by_inbound_id
import random
import time
import os

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

# Default limit of simultaneous IPs per client entry.
DEFAULT_CLIENT_IP_LIMIT = int(os.getenv("XUI_CLIENT_IP_LIMIT", "6"))

# Simple in-process session cache
_SESSION_CACHE = {
    "session": None,
    "ts": 0.0,
}

# Client info cache to reduce XUI calls. Keyed by (email, inbound_id).
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


def _build_client_payload(
    email: str,
    telegram_id: int,
    expiry_ms: int,
    service=None,
    template_client: Optional[dict] = None,
):
    """Собрать payload клиента для XUI addClient/updateClient."""
    template = template_client or {}
    client_uuid = str(uuid.uuid4())

    def _to_int(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    payload = {
        "id": client_uuid,
        "email": email,
        "limitIp": DEFAULT_CLIENT_IP_LIMIT,
        "totalGB": _to_int(template.get("totalGB"), default=0),
        "expiryTime": _to_int(expiry_ms, default=0),
        "enable": bool(template.get("enable", True)),
        "tgId": str(telegram_id),
        "subId": email,
        "reset": _to_int(template.get("reset"), default=0),
    }

    protocol = (getattr(service, "protocol", "") or "").lower()
    if protocol == "vless":
        payload["flow"] = template.get("flow") or "xtls-rprx-vision"
    elif protocol == "vmess":
        alter_id = template.get("alterId") or template.get("aid") or 0
        payload["alterId"] = _to_int(alter_id, default=0)
        security_value = template.get("security")
        if security_value:
            payload["security"] = security_value
    else:
        if template.get("flow"):
            payload["flow"] = template["flow"]

    return payload, client_uuid

def add_client(session, telegram_id, months):
    """Создать клиента с email=telegram_id на указанный срок (месяцы). Возвращает client_id и результат."""
    if months is None:
        raise ValueError("Необходимо указать срок действия (months)")
    url = f"{XUI_URL}/panel/api/inbounds/addClient"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    now = datetime.now()
    expiry_dt = int((now + relativedelta(months=months)).timestamp() * 1000)
    email = str(telegram_id)
    if check_if_client_exists(session, telegram_id):
        logging.warning(f"Клиент с email={email} уже существует. Пропускаем создание.")
        return {"error": "Client already exists", "client_id": None}
    service = get_service_by_inbound_id(1)
    client_payload, client_id = _build_client_payload(
        email,
        telegram_id,
        expiry_dt,
        service=service,
    )
    settings = {"clients": [client_payload]}
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

def add_client_days(session, telegram_id, days, inbound_id: int = 1, email: str = None):
    """Создать клиента на указанное число дней (days). Возвращает client_id и результат."""
    if days is None or int(days) <= 0:
        raise ValueError("Необходимо указать положительное число дней")
    url = f"{XUI_URL}/panel/api/inbounds/addClient"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    now = datetime.now()
    expiry_dt = int((now + relativedelta(days=days)).timestamp() * 1000)
    email = email or str(telegram_id)
    if check_if_client_exists(session, email, inbound_id=inbound_id):
        logging.warning(f"Клиент с email={email} уже существует. Пропускаем создание.")
        return {"error": "Client already exists", "client_id": None}
    service = get_service_by_inbound_id(inbound_id)
    client_payload, client_id = _build_client_payload(
        email,
        telegram_id,
        expiry_dt,
        service=service,
    )
    settings = {"clients": [client_payload]}
    data = {
        "id": inbound_id,
        "settings": json.dumps(settings)
    }
    try:
        response = session.post(url, json=data, headers=headers, timeout=5)
        response.raise_for_status()
        logging.info(f"Клиент {email} успешно добавлен на {days} дн.")
        invalidate_client_cache(email)
        return {"client_id": client_id, "result": response.json()}
    except requests.RequestException as e:
        logging.error(f"Ошибка при добавлении клиента: {e}")
        return {"error": str(e), "client_id": None}


def add_client_with_expiry(
    session,
    telegram_id,
    expiry_time_ms: int,
    inbound_id: int,
    email: str = None,
    template_client: Optional[dict] = None,
):
    """Создать клиента с заданным временем истечения (в мс)."""
    url = f"{XUI_URL}/panel/api/inbounds/addClient"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    email = email or str(telegram_id)
    service = get_service_by_inbound_id(inbound_id)
    client_payload, client_id = _build_client_payload(
        email,
        telegram_id,
        expiry_time_ms,
        service=service,
        template_client=template_client,
    )
    settings = {"clients": [client_payload]}
    data = {
        "id": inbound_id,
        "settings": json.dumps(settings)
    }
    try:
        response = session.post(url, json=data, headers=headers, timeout=5)
        response.raise_for_status()
        logging.info(
            "Клиент %s добавлен в inbound %s с expiry=%s",
            email,
            inbound_id,
            expiry_time_ms,
        )
        invalidate_client_cache(email)
        return {"client_id": client_id, "result": response.json()}
    except requests.RequestException as e:
        logging.error(
            "Ошибка при добавлении клиента %s в inbound %s с заданным expiry: %s",
            email,
            inbound_id,
            e,
        )
        return {"error": str(e), "client_id": None}

def check_if_client_exists(session, identifier, inbound_id: int = None):
    """Проверить, есть ли клиент с таким email (или telegram_id)."""
    url = f"{XUI_URL}/panel/api/inbounds/list"
    headers = {"Accept": "application/json"}
    email = str(identifier)
    try:
        response = session.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        inbounds = response.json().get('obj', [])
        for inbound in inbounds:
            if inbound_id is not None and int(inbound.get('id')) != int(inbound_id):
                continue
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

def get_client_info(session, identifier, inbound_id: int = None):
    """
    Получить inbound_id и client по email (telegram_id).
    """
    import json
    import logging
    url = f"{XUI_URL}/panel/api/inbounds/list"
    headers = {"Accept": "application/json"}
    email = str(identifier)
    # serve from cache if fresh
    now_ts = time.time()
    cache_key = (email, int(inbound_id)) if inbound_id is not None else (email, None)
    cached = _CLIENT_CACHE.get(cache_key)
    if cached and (now_ts - cached.get("ts", 0)) < CLIENT_INFO_TTL_SEC:
        return cached.get("inbound"), cached.get("client")
    response = session.get(url, headers=headers, timeout=5)
    response.raise_for_status()
    inbounds = response.json().get('obj', [])
    for inbound in inbounds:
        inbound_id_value = inbound.get('id')
        if inbound_id is not None and int(inbound_id_value) != int(inbound_id):
            continue
        settings = inbound.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        clients = settings.get("clients", [])
        for client in clients:
            if client.get('email') == email:
                logging.debug("Inbound fetched for email=%s (inbound=%s)", email, inbound_id_value)
                _CLIENT_CACHE[cache_key] = {"inbound": inbound, "client": client, "ts": now_ts}
                return inbound, client
    return None, None

def invalidate_client_cache(email: str):
    email_str = str(email)
    try:
        keys_to_drop = [
            key for key in list(_CLIENT_CACHE)
            if (isinstance(key, tuple) and key and key[0] == email_str) or key == email_str
        ]
        for key in keys_to_drop:
            _CLIENT_CACHE.pop(key, None)
    except Exception:
        pass

def _ensure_dict(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value or {}


def _first_non_empty(*candidates):
    for candidate in candidates:
        if isinstance(candidate, (list, tuple)):
            for item in candidate:
                if isinstance(item, str) and item.strip():
                    return item.strip()
        elif isinstance(candidate, str):
            stripped = candidate.strip()
            if not stripped:
                continue
            if stripped.startswith('[') or stripped.startswith('{'):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, (list, tuple)):
                        for item in parsed:
                            if isinstance(item, str) and item.strip():
                                return item.strip()
                    elif isinstance(parsed, str) and parsed.strip():
                        return parsed.strip()
                    continue
                except json.JSONDecodeError:
                    pass
            return stripped
        elif candidate:
            return candidate
    return None


def _sanitize_host(candidate):
    if not candidate:
        return None
    candidate = str(candidate).strip()
    if not candidate:
        return None
    if candidate.startswith('[') or candidate.startswith('{'):
        return None
    if any(ch in candidate for ch in ' /\\'):
        return None
    if '.' not in candidate and not any(ch.isdigit() for ch in candidate):
        return None
    return candidate


def _resolve_stream_settings(inbound: dict):
    stream_settings = _ensure_dict(inbound.get('streamSettings'))
    network = stream_settings.get('network', 'tcp')
    security = stream_settings.get('security', '')
    return stream_settings, network, security


def _derive_host_and_port(inbound: dict, service, dest_host=None, dest_port=None):
    host_candidates = [
        getattr(service, "server_host", None) if service else None,
        inbound.get('listen'),
        inbound.get('remark'),
        SERVER_HOST,
        dest_host,
    ]

    host = None
    for candidate in host_candidates:
        sanitized = _sanitize_host(candidate)
        if sanitized:
            host = sanitized
            break
    if not host:
        host = SERVER_HOST

    port_value = inbound.get('port')
    try:
        port = int(port_value)
    except (TypeError, ValueError):
        port = None
    if port is None and dest_port is not None:
        port = dest_port
    if port is None:
        port = SERVER_PORT
    return host, port


def _generate_vless_link(inbound: dict, client: dict, service) -> str:
    email = client.get('email')
    uuid_value = client.get('id')
    flow = (client.get('flow') or '').strip()

    stream_settings, network, security = _resolve_stream_settings(inbound)
    if not security:
        security = 'reality'

    reality_settings = _ensure_dict(stream_settings.get('realitySettings'))
    nested_settings = _ensure_dict(reality_settings.get('settings'))

    dest_value = _first_non_empty(
        reality_settings.get('dest'),
        nested_settings.get('dest'),
    )
    dest_host = None
    dest_port = None
    if isinstance(dest_value, str):
        dest_clean = dest_value.strip()
        if dest_clean:
            if ':' in dest_clean:
                host_part, port_part = dest_clean.split(':', 1)
                if host_part.strip():
                    dest_host = host_part.strip()
                port_part = port_part.strip()
                if port_part.isdigit():
                    dest_port = int(port_part)
            else:
                dest_host = dest_clean

    host, port = _derive_host_and_port(inbound, service, dest_host, dest_port)

    public_key = _first_non_empty(
        reality_settings.get('publicKey'),
        nested_settings.get('publicKey'),
        REALITY_PBK,
    )
    short_id = _first_non_empty(
        reality_settings.get('shortIds'),
        nested_settings.get('shortIds'),
        reality_settings.get('shortId'),
        nested_settings.get('shortId'),
        REALITY_SID,
    )
    sni = _first_non_empty(
        reality_settings.get('serverNames'),
        nested_settings.get('serverNames'),
        reality_settings.get('serverName'),
        nested_settings.get('serverName'),
        reality_settings.get('sni'),
        nested_settings.get('sni'),
        REALITY_SNI,
    )
    fingerprint = _first_non_empty(
        stream_settings.get('fingerprint'),
        reality_settings.get('fingerprint'),
        nested_settings.get('fingerprint'),
        reality_settings.get('fp'),
        nested_settings.get('fp'),
        REALITY_FP,
    )

    public_key = public_key or REALITY_PBK
    short_id = short_id or REALITY_SID
    sni = sni or REALITY_SNI
    fingerprint = fingerprint or REALITY_FP

    return (
        f"vless://{uuid_value}@{host}:{port}?type={network}&security={security}"
        f"&pbk={public_key}&fp={fingerprint}&sni={sni}&sid={short_id}&spx=%2F&flow={flow}#vles-{email}"
    )


def _generate_vmess_link(inbound: dict, client: dict, service) -> str:
    email = client.get('email')
    uuid_value = client.get('id') or client.get('uuid')
    stream_settings, network, security = _resolve_stream_settings(inbound)
    host, port = _derive_host_and_port(inbound, service)

    ws_settings = _ensure_dict(stream_settings.get('wsSettings'))
    grpc_settings = _ensure_dict(stream_settings.get('grpcSettings'))
    http_settings = _ensure_dict(stream_settings.get('httpSettings'))
    ws_headers = _ensure_dict(ws_settings.get('headers'))

    host_header = _first_non_empty(
        ws_headers.get('Host'),
        ws_headers.get('host'),
    )
    http_host = http_settings.get('host')
    if not host_header and http_host:
        if isinstance(http_host, (list, tuple)):
            host_header = _first_non_empty(*http_host)
        elif isinstance(http_host, str):
            host_header = http_host.strip()

    if host_header:
        host_header = host_header.strip()

    if network == 'ws':
        path = ws_settings.get('path') or '/'
    elif network == 'grpc':
        path = grpc_settings.get('serviceName') or ''
    elif network == 'http':
        path = http_settings.get('path') or '/'
    else:
        path = ws_settings.get('path') or '/'

    tls_enabled = security and security.lower() in {"tls", "xtls"}
    tls_settings = _ensure_dict(stream_settings.get('tlsSettings'))
    sni = _first_non_empty(
        stream_settings.get('sni'),
        tls_settings.get('serverName'),
        inbound.get('sni'),
    )

    alpn_value = stream_settings.get('alpn')
    if isinstance(alpn_value, (list, tuple)) and alpn_value:
        alpn = ','.join(str(item) for item in alpn_value if item)
    else:
        alpn = None

    alter_id = client.get('alterId') or client.get('aid') or 0
    try:
        alter_id = int(alter_id)
    except (TypeError, ValueError):
        alter_id = 0

    scy = client.get('security') or 'auto'
    remark = inbound.get('remark') or (service.name if service else f"vmess-{email}")
    type_field = 'gun' if network == 'grpc' else 'none'
    host_field = host_header or host

    vmess_config = {
        "v": "2",
        "ps": remark,
        "add": host,
        "port": str(port),
        "id": uuid_value,
        "aid": str(alter_id),
        "scy": scy,
        "net": network,
        "type": type_field,
        "host": host_field,
        "path": path or '/',
        "tls": "tls" if tls_enabled else "",
    }

    if tls_enabled and sni:
        vmess_config["sni"] = sni
    if alpn:
        vmess_config["alpn"] = alpn

    encoded = base64.b64encode(json.dumps(vmess_config, ensure_ascii=False).encode("utf-8")).decode("utf-8")
    return f"vmess://{encoded}"


def generate_vless_link(inbound: dict, client: dict) -> str:
    """Собирает ссылку доступа на основе inbound и client (VLESS/VMess)."""
    inbound_id = inbound.get('id')
    service = get_service_by_inbound_id(inbound_id)
    protocol = str(inbound.get('protocol') or "").lower()
    if not protocol and service and getattr(service, "protocol", None):
        protocol = service.protocol.lower()

    if protocol == 'vmess':
        return _generate_vmess_link(inbound, client, service)
    return _generate_vless_link(inbound, client, service)

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
                    # enforce IP limit policy
                    try:
                        if int(updated_client.get('limitIp', 0)) < DEFAULT_CLIENT_IP_LIMIT:
                            updated_client['limitIp'] = DEFAULT_CLIENT_IP_LIMIT
                    except Exception:
                        updated_client['limitIp'] = DEFAULT_CLIENT_IP_LIMIT
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

def extend_client_days(session, telegram_id, days: int, inbound_id: int = None, email: str = None) -> bool:
    """Продлить срок действия клиента на указанное число дней. Не создаёт нового клиента.
    Логика: найти inbound+client по email (telegram_id), взять max(now, currentExpiry) + days.
    """
    if days is None or int(days) <= 0:
        return False
    url_list = f"{XUI_URL}/panel/api/inbounds/list"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    email = email or str(telegram_id)
    try:
        response = session.get(url_list, headers=headers)
        response.raise_for_status()
        inbounds = response.json().get('obj', [])
        for inbound in inbounds:
            inbound_id_value = inbound.get('id')
            if inbound_id is not None and int(inbound_id_value) != int(inbound_id):
                continue
            settings = inbound.get('settings', {})
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
                    # enforce IP limit policy
                    try:
                        if int(updated_client.get('limitIp', 0)) < DEFAULT_CLIENT_IP_LIMIT:
                            updated_client['limitIp'] = DEFAULT_CLIENT_IP_LIMIT
                    except Exception:
                        updated_client['limitIp'] = DEFAULT_CLIENT_IP_LIMIT
                    settings_obj = {"clients": [updated_client]}
                    upd_url = f"{XUI_URL}/panel/api/inbounds/updateClient/{client_id}"
                    data = {"id": inbound_id_value, "settings": json.dumps(settings_obj)}
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