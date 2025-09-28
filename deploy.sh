#!/bin/bash

# VPN Bot - Главный скрипт деплоя
set -e

echo "🚀 VPN Bot - Автоматический деплой"
echo "=================================="

# Проверяем, что мы в корне проекта
if [ ! -f "README.md" ] || [ ! -d "bot" ] || [ ! -d "deploy" ]; then
    echo "❌ Запустите скрипт из корня проекта vpnBot"
    exit 1
fi

# Копируем файлы в корень для деплоя
echo "📁 Подготовка файлов для деплоя..."
cp bot/*.py .
cp deploy/docker-compose.yml .
cp deploy/Dockerfile .
cp deploy/vpnbot.service .
cp utils/monitor.sh .
cp utils/backup.sh .
cp utils/anomaly_check.py .
cp env.example .

echo "✅ Файлы подготовлены"
echo ""
echo "📝 Следующие шаги:"
echo "1. Настройте .env файл:"
echo "   nano .env"
echo ""
echo "2. Запустите бота:"
echo "   docker-compose up -d"
echo ""
echo "3. Проверьте логи:"
echo "   docker-compose logs -f"
echo ""
echo "4. Настройте systemd (опционально):"
echo "   sudo cp vpnbot.service /etc/systemd/system/"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable vpnbot"
echo ""
echo "🎯 Готово к деплою!"
