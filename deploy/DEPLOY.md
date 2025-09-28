# 🚀 Деплой VPN бота на VPS

## 📋 Что нужно

- VPS с Ubuntu 20.04+ или Debian 11+
- Root доступ
- X-UI панель
- YooKassa аккаунт
- Telegram бот (от @BotFather)

## 🚀 Автоматический деплой

### 1. Подключитесь к VPS
```bash
ssh root@YOUR_VPS_IP
```

### 2. Запустите деплой
```bash
wget https://raw.githubusercontent.com/ogSulem/vpnBot/main/deploy/deploy.sh
chmod +x deploy.sh
./deploy.sh
```

### 3. Настройте конфигурацию
```bash
nano /opt/vpnbot/.env
```

**Обязательные настройки:**
```env
# Telegram Bot (получите у @BotFather)
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
ADMIN_IDS=123456789

# X-UI Panel (ваша панель)
XUI_URL=http://YOUR_PANEL_IP:PORT/PATH
XUI_USER=admin
XUI_PASSWORD=your_password

# YooKassa (для платежей)
USE_YOOKASSA=true
YOOKASSA_ACCOUNT_ID=your_shop_id
YOOKASSA_SECRET_KEY=test_your_test_key
YOOKASSA_RETURN_URL=https://t.me/your_bot_username

# Server (ваш сервер)
SERVER_HOST=YOUR_SERVER_IP
SERVER_PORT=443
REALITY_PBK=your_reality_public_key
REALITY_SID=your_reality_short_id
REALITY_SNI=your_reality_sni
REALITY_FP=chrome
```

### 4. Запустите бота
```bash
cd /opt/vpnbot
docker-compose up -d
```

### 5. Проверьте работу
```bash
# Статус
docker-compose ps

# Логи
docker-compose logs -f

# Проверка API
curl -s "https://api.telegram.org/bot$BOT_TOKEN/getMe"
```

## 🛠️ Управление

```bash
# Запуск
systemctl start vpnbot

# Остановка
systemctl stop vpnbot

# Перезапуск
systemctl restart vpnbot

# Статус
systemctl status vpnbot

# Логи
journalctl -u vpnbot -f
```

## 📊 Мониторинг

- ✅ **Автоматическая проверка** каждые 5 минут
- ✅ **Перезапуск при сбоях**
- ✅ **Уведомления админам**
- ✅ **Ежедневные бэкапы** в 2:00

## 🔧 Получение данных

### Telegram Bot
1. Найдите [@BotFather](https://t.me/BotFather)
2. Отправьте `/newbot`
3. Следуйте инструкциям
4. Скопируйте токен

### YooKassa
1. Зарегистрируйтесь на [yookassa.ru](https://yookassa.ru/)
2. Создайте магазин
3. Получите Shop ID и Secret Key

### X-UI Panel
1. Установите X-UI панель
2. Создайте inbound с Reality
3. Скопируйте данные подключения

## 🎯 Готово!

Ваш VPN бот готов к работе! 

**Проверьте:**
1. ✅ Бот отвечает на `/start`
2. ✅ Тестовый период работает
3. ✅ Платежи проходят
4. ✅ VPN ссылки генерируются

**Управление:**
- Логи: `docker-compose logs -f`
- Статус: `docker-compose ps`
- Перезапуск: `systemctl restart vpnbot`