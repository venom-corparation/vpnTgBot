#!/bin/bash

# VPN Bot - Идеальный автоматический деплой из уже склонированного репозитория
set -e

echo "🚀 VPN Bot - Автоматический деплой из локального репозитория"
echo "========================================="

# Обновляем систему
echo "📦 Обновление системы..."
apt update && apt upgrade -y
apt install -y curl wget git nano htop

# Устанавливаем Docker
echo "🐳 Установка Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl start docker
    systemctl enable docker
    usermod -aG docker $USER
else
    echo "Docker уже установлен."
fi

# Проверяем, что скрипт запущен из корня проекта
if [ ! -f "README.md" ] || [ ! -d "bot" ] || [ ! -d "deploy" ]; then
    echo "❌ Запустите скрипт из корня проекта vpnBot (где есть bot/, deploy/, README.md)"
    exit 1
fi

# Файлы уже в корне проекта

# Удаляем старые volumes и контейнеры
echo "🧹 Очистка старых контейнеров и volumes..."
docker-compose down --volumes --remove-orphans || true
docker volume prune -f || true
rm -f users.db

# Создаём .env из примера, если нет
if [ ! -f ".env" ]; then
    cp env.example .env
    echo "Создан .env файл из env.example. Отредактируйте его перед запуском!"
else
    echo ".env файл уже существует"
fi

# Создаём директории для логов и бэкапов
mkdir -p logs backups
sudo chown -R 1000:1000 logs backups

# Права уже установлены выше

# Копируем systemd unit
echo "🔧 Создание systemd сервиса..."
cp deploy/vpnbot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable vpnbot

# Делаем скрипты мониторинга и бэкапа исполняемыми
chmod +x utils/monitor.sh utils/backup.sh

# Настраиваем cron
echo "⏰ Настройка мониторинга и бэкапов..."
(crontab -l 2>/dev/null; echo "*/5 * * * * $(pwd)/utils/monitor.sh") | crontab -
(crontab -l 2>/dev/null; echo "0 2 * * * $(pwd)/utils/backup.sh && $(pwd)/utils/anomaly_check.py") | crontab -

echo "✅ Деплой завершён!"
echo ""
echo "📝 Следующие шаги:"
echo "1. Настройте .env файл:"
echo "   nano .env"
echo ""
echo "2. Запустите бота (создастся volume для users.db):"
echo "   docker-compose build --no-cache"
echo "   docker-compose up -d"
echo ""
echo "3. Проверьте логи:"
echo "   docker-compose logs -f"
echo ""
echo "🎯 Готово к деплою! Управление через systemctl (systemctl start vpnbot) или docker-compose."
