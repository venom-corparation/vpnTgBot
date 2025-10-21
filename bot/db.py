import sqlite3
import json
import re
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, Dict, Any
import logging

from config import XUI_URL
from tariffs import get_service_by_inbound_id, auto_assign_services, get_service
from api import add_client_with_expiry, update_client_with_expiry

DEFAULT_DB_PATH = "/app/data/users.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    date_registered TEXT,
    vpn_email TEXT,
    last_action TEXT
);
CREATE INDEX IF NOT EXISTS idx_users_tg_id ON users(tg_id);
CREATE INDEX IF NOT EXISTS idx_users_vpn_email ON users(vpn_email);

CREATE TABLE IF NOT EXISTS promos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    months INTEGER NOT NULL DEFAULT 0,
    days INTEGER NOT NULL DEFAULT 0,
    max_uses INTEGER NOT NULL DEFAULT 1,
    used_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS promo_redemptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    promo_id INTEGER NOT NULL,
    tg_id INTEGER NOT NULL,
    redeemed_at TEXT,
    UNIQUE(promo_id, tg_id),
    FOREIGN KEY(promo_id) REFERENCES promos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reminders_sent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL,
    expiry_ms INTEGER NOT NULL,
    kind TEXT NOT NULL,
    sent_at TEXT,
    UNIQUE(tg_id, expiry_ms, kind)
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id TEXT UNIQUE,
    tg_id INTEGER NOT NULL,
    plan TEXT,
    days INTEGER,
    amount INTEGER,
    currency TEXT,
    status TEXT,
    applied INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_payments_tg ON payments(tg_id);
CREATE INDEX IF NOT EXISTS idx_payments_payment_id ON payments(payment_id);
"""

@contextmanager
def get_connection(db_path: str = DEFAULT_DB_PATH):
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(SCHEMA_SQL)
        # best-effort migration: ensure days column exists
        try:
            conn.execute("ALTER TABLE promos ADD COLUMN days INTEGER NOT NULL DEFAULT 0;")
        except sqlite3.OperationalError:
            pass
        yield conn
        conn.commit()
    finally:
        conn.close()


def add_user(
    tg_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    date_registered: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    """Insert a new user. Returns user id. If exists, returns existing id."""
    if date_registered is None:
        date_registered = datetime.utcnow().isoformat()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO users (tg_id, username, first_name, last_name, date_registered, vpn_email, last_action)
            VALUES (?, ?, ?, ?, ?, NULL, ?)
            ON CONFLICT(tg_id) DO NOTHING;
            """,
            (tg_id, username, first_name, last_name, date_registered, date_registered),
        )
        if cur.rowcount == 0:
            cur = conn.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
            row = cur.fetchone()
            return int(row[0])
        return cur.lastrowid


def upsert_user_on_start(
    tg_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    now_iso = datetime.utcnow().isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO users (tg_id, username, first_name, last_name, date_registered, vpn_email, last_action)
            VALUES (?, ?, ?, ?, ?, NULL, ?)
            ON CONFLICT(tg_id) DO NOTHING;
            """,
            (tg_id, username, first_name, last_name, now_iso, now_iso),
        )
        conn.execute(
            """
            UPDATE users
            SET username = COALESCE(?, username),
                first_name = COALESCE(?, first_name),
                last_name = COALESCE(?, last_name),
                last_action = ?
            WHERE tg_id = ?
            """,
            (username, first_name, last_name, now_iso, tg_id),
        )
        cur = conn.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
        row = cur.fetchone()
        return int(row[0])


def get_user_by_tg(tg_id: int, db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        cur = conn.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def set_vpn_email(tg_id: int, vpn_email: Optional[str], db_path: str = DEFAULT_DB_PATH) -> bool:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "UPDATE users SET vpn_email = ? WHERE tg_id = ?",
            (vpn_email, tg_id),
        )
        return cur.rowcount > 0




def list_users(limit: int = 100, offset: int = 0, db_path: str = DEFAULT_DB_PATH) -> list:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM users ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(r) for r in cur.fetchall()]


def list_users_with_vpn(db_path: str = DEFAULT_DB_PATH) -> list:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM users WHERE vpn_email IS NOT NULL AND vpn_email <> ''"
        )
        return [dict(r) for r in cur.fetchall()]


def list_users_without_vpn(db_path: str = DEFAULT_DB_PATH) -> list:
    """Получить пользователей без VPN (для уведомлений о неактивности)."""
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM users WHERE vpn_email IS NULL OR vpn_email = ''"
        )
        return [dict(r) for r in cur.fetchall()]


def list_users_with_expired_vpn(db_path: str = DEFAULT_DB_PATH) -> list:
    """Получить пользователей с истекшей подпиской (для уведомлений о неактивности после истечения)."""
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM users WHERE vpn_email IS NOT NULL AND vpn_email <> ''"
        )
        return [dict(r) for r in cur.fetchall()]


def was_reminder_sent(tg_id: int, expiry_ms: int, kind: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "SELECT 1 FROM reminders_sent WHERE tg_id = ? AND expiry_ms = ? AND kind = ?",
            (tg_id, int(expiry_ms), kind),
        )
        return cur.fetchone() is not None


def was_inactivity_reminder_sent(tg_id: int, reminder_key: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    """Проверить, отправлялось ли уведомление о неактивности."""
    with get_connection(db_path) as conn:
        # Если передано число, формируем ключ для новых пользователей
        if isinstance(reminder_key, int):
            kind = f"inactive_{reminder_key}d"
        else:
            # Если передана строка, используем как есть (для expired_*)
            kind = reminder_key
            
        cur = conn.execute(
            "SELECT 1 FROM reminders_sent WHERE tg_id = ? AND kind = ?",
            (tg_id, kind),
        )
        return cur.fetchone() is not None


def mark_inactivity_reminder_sent(tg_id: int, reminder_key, db_path: str = DEFAULT_DB_PATH) -> None:
    """Отметить, что уведомление о неактивности отправлено."""
    from datetime import datetime
    now_iso = datetime.utcnow().isoformat()
    
    # Если передано число, формируем ключ для новых пользователей
    if isinstance(reminder_key, int):
        kind = f"inactive_{reminder_key}d"
    else:
        # Если передана строка, используем как есть (для expired_*)
        kind = reminder_key
    
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO reminders_sent (tg_id, expiry_ms, kind, sent_at) VALUES (?, ?, ?, ?)",
            (tg_id, 0, kind, now_iso),
        )


def mark_reminder_sent(tg_id: int, expiry_ms: int, kind: str, db_path: str = DEFAULT_DB_PATH) -> None:
    from datetime import datetime
    now_iso = datetime.utcnow().isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO reminders_sent (tg_id, expiry_ms, kind, sent_at) VALUES (?, ?, ?, ?)",
            (tg_id, int(expiry_ms), kind, now_iso),
        )


# ---- Promos (days-based) ----

def add_promo(code: str, days: int = 1, max_uses: int = 1, db_path: str = DEFAULT_DB_PATH) -> bool:
    """
    Создать промокод. Если промокод с таким кодом уже существует и ИСЧЕРПАН
    (used_count >= max_uses), то переиспользовать его: обнулить used_count,
    обновить days/max_uses и удалить старые активации (promo_redemptions),
    чтобы промокод можно было активировать заново теми же пользователями.
    Если промокод существует, но ещё не исчерпан — вернуть False.
    """
    now_iso = datetime.utcnow().isoformat()
    with get_connection(db_path) as conn:
        # Попытка вставки нового промокода
        try:
            conn.execute(
                """
                INSERT INTO promos (code, months, days, max_uses, used_count, created_at, updated_at)
                VALUES (?, 0, ?, ?, 0, ?, ?)
                """,
                (code, days, max_uses, now_iso, now_iso),
            )
            return True
        except sqlite3.IntegrityError:
            # Уже существует — проверяем состояние
            cur = conn.execute("SELECT * FROM promos WHERE code = ?", (code,))
            row = cur.fetchone()
            if not row:
                return False
            promo = dict(row)
            if int(promo.get("used_count", 0)) >= int(promo.get("max_uses", 0)):
                # Исчерпан — сбрасываем
                conn.execute(
                    "UPDATE promos SET days = ?, max_uses = ?, used_count = 0, updated_at = ? WHERE id = ?",
                    (int(days), int(max_uses), now_iso, int(promo["id"]))
                )
                # Удаляем старые активации, чтобы можно было активировать снова
                conn.execute(
                    "DELETE FROM promo_redemptions WHERE promo_id = ?",
                    (int(promo["id"]),)
                )
                return True
            # Не исчерпан — нельзя создать такой же код заново
            return False


def get_promo(code: str, db_path: str = DEFAULT_DB_PATH):
    with get_connection(db_path) as conn:
        cur = conn.execute("SELECT * FROM promos WHERE code = ?", (code,))
        row = cur.fetchone()
        return dict(row) if row else None


def redeem_promo(code: str, tg_id: int, db_path: str = DEFAULT_DB_PATH):
    now_iso = datetime.utcnow().isoformat()
    with get_connection(db_path) as conn:
        cur = conn.execute("SELECT * FROM promos WHERE code = ?", (code,))
        promo = cur.fetchone()
        if not promo:
            return {"ok": False, "reason": "not_found"}
        promo = dict(promo)
        if promo["used_count"] >= promo["max_uses"]:
            return {"ok": False, "reason": "exhausted"}
        cur = conn.execute(
            "SELECT 1 FROM promo_redemptions WHERE promo_id = ? AND tg_id = ?",
            (promo["id"], tg_id),
        )
        if cur.fetchone():
            return {"ok": False, "reason": "already_redeemed"}
        conn.execute(
            "INSERT INTO promo_redemptions (promo_id, tg_id, redeemed_at) VALUES (?, ?, ?)",
            (promo["id"], tg_id, now_iso),
        )
        conn.execute(
            "UPDATE promos SET used_count = used_count + 1, updated_at = ? WHERE id = ?",
            (now_iso, promo["id"]),
        )
        return {"ok": True, "days": int(promo.get("days", 0)) or int(promo.get("months", 0))*30 }


def count_users(db_path: str = DEFAULT_DB_PATH) -> int:
    with get_connection(db_path) as conn:
        cur = conn.execute("SELECT COUNT(*) FROM users")
        return int(cur.fetchone()[0])


# ---- Payments ----

def save_payment(
    payment_id: str,
    tg_id: int,
    plan: str,
    days: int,
    amount: int,
    currency: str,
    status: str,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    now_iso = datetime.utcnow().isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO payments (payment_id, tg_id, plan, days, amount, currency, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(payment_id) DO UPDATE SET
                tg_id=excluded.tg_id,
                plan=excluded.plan,
                days=excluded.days,
                amount=excluded.amount,
                currency=excluded.currency,
                status=excluded.status,
                updated_at=excluded.updated_at
            """,
            (payment_id, tg_id, plan, int(days), int(amount), currency, status, now_iso, now_iso),
        )


def update_payment_status(payment_id: str, status: str, db_path: str = DEFAULT_DB_PATH) -> None:
    now_iso = datetime.utcnow().isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE payments SET status = ?, updated_at = ? WHERE payment_id = ?",
            (status, now_iso, payment_id),
        )


def get_payment(payment_id: str, db_path: str = DEFAULT_DB_PATH):
    with get_connection(db_path) as conn:
        cur = conn.execute("SELECT * FROM payments WHERE payment_id = ?", (payment_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def mark_payment_applied(payment_id: str, db_path: str = DEFAULT_DB_PATH) -> None:
    now_iso = datetime.utcnow().isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE payments SET applied = 1, updated_at = ? WHERE payment_id = ?",
            (now_iso, payment_id),
        )


def count_users_with_vpn(db_path: str = DEFAULT_DB_PATH) -> int:
    with get_connection(db_path) as conn:
        cur = conn.execute("SELECT COUNT(*) FROM users WHERE vpn_email IS NOT NULL AND vpn_email <> ''")
        return int(cur.fetchone()[0])


def count_promos(db_path: str = DEFAULT_DB_PATH) -> int:
    with get_connection(db_path) as conn:
        cur = conn.execute("SELECT COUNT(*) FROM promos")
        return int(cur.fetchone()[0])


def sum_promo_uses(db_path: str = DEFAULT_DB_PATH) -> int:
    with get_connection(db_path) as conn:
        cur = conn.execute("SELECT COALESCE(SUM(used_count),0) FROM promos")
        return int(cur.fetchone()[0])


def list_promos(db_path: str = DEFAULT_DB_PATH, active_only: bool = True, limit: int = 50, offset: int = 0) -> list:
    with get_connection(db_path) as conn:
        if active_only:
            cur = conn.execute(
                """
                SELECT * FROM promos
                WHERE used_count < max_uses
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM promos ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        return [dict(r) for r in cur.fetchall()]


def sync_users_with_xui(session, db_path: str = DEFAULT_DB_PATH) -> dict:
    """
    Синхронизирует БД с XUI панелью.
    Возвращает статистику синхронизации.
    """
    if not session:
        return {"error": "No XUI session"}
    
    stats = {
        "users_in_db": 0,
        "users_in_xui": 0,
        "synced": 0,
        "cleared": 0,
        "errors": 0,
        "extra_clients_added": 0,
    }
    
    try:
        # Получаем всех пользователей из XUI (по всем инбаундам)
        url = f"{XUI_URL}/panel/api/inbounds/list"
        headers = {"Accept": "application/json"}
        response = session.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        inbounds = response.json().get('obj', [])
        
        def extract_tg_id(email: str) -> Optional[int]:
            if not email:
                return None
            match = re.match(r"(\d+)", str(email))
            if not match:
                return None
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                return None

        xui_users: Dict[int, Dict[str, Any]] = {}
        inbound_clients: Dict[int, Dict[int, Dict[str, Any]]] = {}
        for inbound in inbounds:
            inbound_id_value = inbound.get('id')
            try:
                inbound_id_int = int(inbound_id_value)
            except (TypeError, ValueError):
                continue
            service = get_service_by_inbound_id(inbound_id_value)
            priority = getattr(service, "sync_priority", 5) if service else 5
            settings = inbound.get('settings', {})
            if isinstance(settings, str):
                settings = json.loads(settings)
            clients = settings.get("clients", [])
            inbound_clients.setdefault(inbound_id_int, {})
            for client in clients:
                email = client.get('email')
                tg_id = extract_tg_id(email)
                if tg_id is None:
                    continue
                inbound_clients[inbound_id_int][tg_id] = client
                record = xui_users.get(tg_id)
                if record is None or priority < record["priority"]:
                    xui_users[tg_id] = {
                        "email": email,
                        "priority": priority,
                        "client": client,
                        "inbound_id": inbound_id_int,
                    }

        stats["users_in_xui"] = len(xui_users)

        # Получаем всех пользователей из БД
        with get_connection(db_path) as conn:
            cur = conn.execute("SELECT tg_id, vpn_email FROM users")
            db_users = {int(row[0]): row[1] for row in cur.fetchall()}

        stats["users_in_db"] = len(db_users)

        # Сопоставляем пользователей XUI с БД
        for tg_id, vpn_email in db_users.items():
            try:
                record = xui_users.get(tg_id)
                if record:
                    desired_email = record.get("email")
                    if vpn_email != desired_email:
                        set_vpn_email(tg_id, desired_email, db_path=db_path)
                    stats["synced"] += 1
                else:
                    if vpn_email:
                        set_vpn_email(tg_id, None, db_path=db_path)
                        stats["cleared"] += 1
            except Exception as e:
                logging.error(f"Ошибка синхронизации пользователя {tg_id}: {e}")
                stats["errors"] += 1

        # Дополняем пользователей отсутствующими автоматическими inbound-ами
        extra_services = auto_assign_services()
        for service in extra_services:
            try:
                inbound_id_int = int(service.inbound_id)
            except (TypeError, ValueError):
                continue

            target_keys = getattr(service, "auto_assign_for_services", ())
            target_inbound_ids = []
            for key in target_keys:
                target_service = get_service(key)
                if target_service is None:
                    continue
                try:
                    target_inbound_ids.append(int(target_service.inbound_id))
                except (TypeError, ValueError):
                    continue

            existing_clients_map = inbound_clients.get(inbound_id_int, {})
            for tg_id, record in xui_users.items():
                if target_inbound_ids:
                    required_clients = [
                        inbound_clients.get(target_inbound_id, {}).get(tg_id)
                        for target_inbound_id in target_inbound_ids
                    ]
                    has_required_service = any(client is not None for client in required_clients)
                    if not has_required_service:
                        continue
                else:
                    required_clients = []
                existing_client = existing_clients_map.get(tg_id)
                base_client = record.get("client") if record else None

                template_candidates = []
                if base_client:
                    template_candidates.append(base_client)
                if existing_client:
                    template_candidates.append(existing_client)
                if target_inbound_ids:
                    template_candidates.extend(client for client in required_clients if client)
                template_client = None
                if template_candidates:
                    def _expiry_ms(client_dict):
                        value = client_dict.get('expiryTime') if isinstance(client_dict, dict) else 0
                        try:
                            return int(value or 0)
                        except (TypeError, ValueError):
                            return 0
                    template_client = max(template_candidates, key=_expiry_ms)

                if not template_client:
                    continue

                email_value = service.email_for_user(tg_id)
                if existing_client is not None:
                    current_expiry_raw = existing_client.get('expiryTime') if isinstance(existing_client, dict) else 0
                    try:
                        current_expiry = int(current_expiry_raw or 0)
                    except (TypeError, ValueError):
                        current_expiry = 0
                    if expiry_ms > current_expiry:
                        try:
                            result = update_client_with_expiry(
                                session,
                                tg_id,
                                expiry_ms,
                                inbound_id_int,
                                existing_client=existing_client,
                                email=email_value,
                                template_client=template_client,
                            )
                        except Exception as e:
                            logging.error(
                                "Ошибка при обновлении пользователя %s в inbound %s: %s",
                                tg_id,
                                inbound_id_int,
                                e,
                            )
                            stats["errors"] += 1
                            continue

                        if isinstance(result, dict) and not result.get("error"):
                            existing_client['expiryTime'] = expiry_ms
                            stats["synced"] += 1
                        else:
                            stats["errors"] += 1
                    continue

                if any(
                    str(client.get('email')) == email_value
                    for client in existing_clients_map.values()
                ):
                    continue

                expiry_raw = template_client.get('expiryTime') if isinstance(template_client, dict) else 0
                try:
                    expiry_ms = int(expiry_raw or 0)
                except (TypeError, ValueError):
                    expiry_ms = 0
                if expiry_ms < 0:
                    expiry_ms = 0

                try:
                    result = add_client_with_expiry(
                        session,
                        tg_id,
                        expiry_ms,
                        inbound_id_int,
                        email=email_value,
                        template_client=template_client,
                    )
                except Exception as e:
                    logging.error(
                        "Ошибка при добавлении пользователя %s в inbound %s: %s",
                        tg_id,
                        inbound_id_int,
                        e,
                    )
                    stats["errors"] += 1
                    continue

                if isinstance(result, dict) and result.get("client_id"):
                    stats["extra_clients_added"] += 1
                    logging.info(
                        "Синхронизация: добавлен пользователь %s в inbound %s",
                        tg_id,
                        inbound_id_int,
                    )
                    inbound_clients.setdefault(inbound_id_int, {})[tg_id] = {
                        "email": email_value,
                    }
                else:
                    stats["errors"] += 1

        # Добавляем отсутствующих пользователей из XUI в БД
        missing_in_db = set(xui_users.keys()).difference(db_users.keys())
        for tg_id in missing_in_db:
            try:
                record = xui_users.get(tg_id)
                email_value = record.get("email") if record else None
                upsert_user_on_start(tg_id=tg_id, db_path=db_path)
                if email_value:
                    set_vpn_email(tg_id, email_value, db_path=db_path)
                stats["synced"] += 1
            except Exception as e:
                logging.error(f"Ошибка добавления пользователя {tg_id} из XUI: {e}")
                stats["errors"] += 1

        # Обновляем счётчик пользователей в БД после синхронизации
        with get_connection(db_path) as conn:
            cur = conn.execute("SELECT COUNT(*) FROM users")
            stats["users_in_db"] = int(cur.fetchone()[0])
        
        return stats
        
    except Exception as e:
        logging.error(f"Ошибка синхронизации: {e}")
        return {"error": str(e)}
