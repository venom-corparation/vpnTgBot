import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Panel creds (важные)
XUI_URL = os.getenv("XUI_URL")
XUI_USER = os.getenv("XUI_USER")
XUI_PASSWORD = os.getenv("XUI_PASSWORD")

# X-UI API endpoints
XUI_HOST = XUI_URL.replace("http://", "").replace("https://", "").split("/")[0] if XUI_URL else "127.0.0.1:54321"
XUI_USERNAME = XUI_USER
XUI_PASSWORD = XUI_PASSWORD

# Comma-separated Telegram IDs, e.g. "123,456"
_admin_ids_raw = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS = []
if _admin_ids_raw:
    try:
        ADMIN_IDS = [int(x) for x in _admin_ids_raw.split(",") if x.strip()]
    except ValueError:
        ADMIN_IDS = []
# Rate limit (per seconds window)
RATE_MAX_ACTIONS = int(os.getenv("RATE_MAX_ACTIONS", "3"))
RATE_WINDOW_SEC = int(os.getenv("RATE_WINDOW_SEC", "1"))

# Payments
PROVIDER_TOKEN = os.getenv("PROVIDER_TOKEN", "")
CURRENCY = os.getenv("CURRENCY", "RUB")

# YooKassa Smart Payment
YOOKASSA_ACCOUNT_ID = os.getenv("YOOKASSA_ACCOUNT_ID", "")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "")
YOOKASSA_RETURN_URL = os.getenv("YOOKASSA_RETURN_URL", "https://example.com/return")
USE_YOOKASSA = os.getenv("USE_YOOKASSA", "false").lower() == "true"

# Caching and performance
CLIENT_INFO_TTL_SEC = int(os.getenv("CLIENT_INFO_TTL_SEC", "300"))  # 5 minutes
XUI_LOGIN_RETRIES = int(os.getenv("XUI_LOGIN_RETRIES", "3"))
XUI_LOGIN_TIMEOUT = int(os.getenv("XUI_LOGIN_TIMEOUT", "10"))
XUI_LOGIN_COOLDOWN_SEC = int(os.getenv("XUI_LOGIN_COOLDOWN_SEC", "60"))

# Server/link fallback (меняется при миграции сервера)
SERVER_HOST = os.getenv("SERVER_HOST", "77.110.118.156")
SERVER_PORT = int(os.getenv("SERVER_PORT", "443"))
REALITY_PBK = os.getenv("REALITY_PBK", "a6A2wRX9g1ZW17yG6kp4_tMffxz4hddSAVHXRabkfSo")
REALITY_SID = os.getenv("REALITY_SID", "cc0f3cb1c6")
REALITY_SNI = os.getenv("REALITY_SNI", "yahoo.com")
REALITY_FP = os.getenv("REALITY_FP", "chrome")

