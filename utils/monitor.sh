#!/bin/bash

# =============================================================================
# VPN Bot Monitor Script
# Автоматический мониторинг и восстановление работы бота
# =============================================================================

PROJECT_DIR="/opt/vpnbot"
LOG_FILE="/var/log/vpnbot-monitor.log"
MAX_LOG_SIZE=100  # MB
DISK_THRESHOLD=80  # %

# Функции логирования
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a $LOG_FILE
}

log_error() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - ERROR: $1" | tee -a $LOG_FILE
}

log_warning() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - WARNING: $1" | tee -a $LOG_FILE
}

# Функция отправки уведомления админу
notify_admin() {
    local message="$1"
    
    if [ -f "$PROJECT_DIR/.env" ]; then
        source "$PROJECT_DIR/.env"
        if [ ! -z "$BOT_TOKEN" ] && [ ! -z "$ADMIN_IDS" ]; then
            ADMIN_ID=$(echo $ADMIN_IDS | cut -d',' -f1)
            curl -s "https://api.telegram.org/bot$BOT_TOKEN/sendMessage?chat_id=$ADMIN_ID&text=$message" > /dev/null 2>&1 || true
        fi
    fi
}

# Проверка статуса контейнера
check_container_status() {
    cd "$PROJECT_DIR"
    
    if ! docker-compose ps | grep -q "Up"; then
        log_error "Bot container is down! Restarting..."
        docker-compose restart
        
        if docker-compose ps | grep -q "Up"; then
            log "Bot container restarted successfully"
            notify_admin "🚨 VPN Bot перезапущен автоматически"
        else
            log_error "Failed to restart bot container"
            notify_admin "❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось перезапустить VPN Bot"
        fi
    else
        log "Bot container is running normally"
    fi
}

# Проверка использования диска
check_disk_usage() {
    local disk_usage=$(df /opt | tail -1 | awk '{print $5}' | sed 's/%//')
    
    if [ $disk_usage -gt $DISK_THRESHOLD ]; then
        log_warning "Disk usage is ${disk_usage}% (threshold: ${DISK_THRESHOLD}%)"
        notify_admin "⚠️ ВНИМАНИЕ: Использование диска ${disk_usage}%"
    fi
}

# Проверка и ротация логов
check_log_rotation() {
    local log_file="$PROJECT_DIR/logs/bot.log"
    
    if [ -f "$log_file" ]; then
        local log_size=$(du -m "$log_file" | cut -f1)
        
        if [ $log_size -gt $MAX_LOG_SIZE ]; then
            log_warning "Bot log size is ${log_size}MB (max: ${MAX_LOG_SIZE}MB). Rotating..."
            
            # Создаем архив старого лога
            mv "$log_file" "${log_file}.$(date +%Y%m%d_%H%M%S)"
            touch "$log_file"
            
            # Перезапускаем контейнер для применения изменений
            cd "$PROJECT_DIR"
            docker-compose restart
            
            log "Log rotated and container restarted"
        fi
    fi
}

# Проверка здоровья бота
check_bot_health() {
    if [ -f "$PROJECT_DIR/.env" ]; then
        source "$PROJECT_DIR/.env"
        
        if [ ! -z "$BOT_TOKEN" ]; then
            # Проверяем доступность API Telegram
            local response=$(curl -s -w "%{http_code}" -o /dev/null "https://api.telegram.org/bot$BOT_TOKEN/getMe" --max-time 10)
            
            if [ "$response" != "200" ]; then
                log_error "Bot API health check failed (HTTP $response)"
                notify_admin "⚠️ Проблема с API Telegram (HTTP $response)"
            else
                log "Bot API health check passed"
            fi
        fi
    fi
}

# Проверка памяти
check_memory_usage() {
    local memory_usage=$(free | grep Mem | awk '{printf "%.0f", $3/$2 * 100.0}')
    
    if [ $memory_usage -gt 90 ]; then
        log_warning "Memory usage is ${memory_usage}%"
        notify_admin "⚠️ ВНИМАНИЕ: Использование памяти ${memory_usage}%"
    fi
}

# Мониторинг трафика (1 раз в день)
check_traffic_monitoring() {
    log "Running daily traffic monitoring..."
    
    # Запускаем Python скрипт для мониторинга трафика
    if [ -f "$PROJECT_DIR/anomaly_check.py" ]; then
        cd "$PROJECT_DIR"
        python3 anomaly_check.py >> "$LOG_FILE" 2>&1
        if [ $? -eq 0 ]; then
            log "Daily traffic monitoring completed successfully"
        else
            log_error "Daily traffic monitoring failed"
        fi
    else
        log_warning "Traffic monitoring script not found"
    fi
}

# Очистка старых логов
cleanup_old_logs() {
    find "$PROJECT_DIR/logs" -name "*.log.*" -mtime +7 -delete 2>/dev/null || true
    find "$PROJECT_DIR/backups" -name "*.db" -mtime +30 -delete 2>/dev/null || true
}

# Основная функция мониторинга
main() {
    log "Starting VPN Bot monitoring..."
    
    check_container_status
    check_disk_usage
    check_log_rotation
    check_bot_health
    check_memory_usage
    check_traffic_monitoring
    cleanup_old_logs
    
    log "VPN Bot monitoring completed"
}

# Запуск
main "$@"
