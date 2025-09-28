#!/bin/bash

# =============================================================================
# VPN Bot Backup Script
# Автоматическое создание бэкапов базы данных и конфигурации
# =============================================================================

PROJECT_DIR="/opt/vpnbot"
BACKUP_DIR="/opt/vpnbot/backups"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=7

# Функции логирования
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_error() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - ERROR: $1"
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

# Создание директории бэкапа
create_backup_dir() {
    if [ ! -d "$BACKUP_DIR" ]; then
        mkdir -p "$BACKUP_DIR"
        log "Created backup directory: $BACKUP_DIR"
    fi
}

# Бэкап базы данных
backup_database() {
    local db_file="$PROJECT_DIR/users.db"
    
    if [ -f "$db_file" ]; then
        local backup_file="$BACKUP_DIR/users_$DATE.db"
        cp "$db_file" "$backup_file"
        
        if [ $? -eq 0 ]; then
            log "Database backup created: users_$DATE.db"
            return 0
        else
            log_error "Failed to backup database"
            return 1
        fi
    else
        log "Database file not found, skipping backup"
        return 1
    fi
}

# Бэкап конфигурации
backup_config() {
    local config_file="$PROJECT_DIR/.env"
    
    if [ -f "$config_file" ]; then
        local backup_file="$BACKUP_DIR/env_$DATE"
        cp "$config_file" "$backup_file"
        
        if [ $? -eq 0 ]; then
            log "Configuration backup created: env_$DATE"
            return 0
        else
            log_error "Failed to backup configuration"
            return 1
        fi
    else
        log "Configuration file not found, skipping backup"
        return 1
    fi
}

# Бэкап логов
backup_logs() {
    local logs_dir="$PROJECT_DIR/logs"
    
    if [ -d "$logs_dir" ] && [ "$(ls -A $logs_dir)" ]; then
        local backup_file="$BACKUP_DIR/logs_$DATE.tar.gz"
        tar -czf "$backup_file" -C "$PROJECT_DIR" logs/
        
        if [ $? -eq 0 ]; then
            log "Logs backup created: logs_$DATE.tar.gz"
            return 0
        else
            log_error "Failed to backup logs"
            return 1
        fi
    else
        log "Logs directory not found or empty, skipping backup"
        return 1
    fi
}

# Бэкап всего проекта
backup_full_project() {
    local backup_file="$BACKUP_DIR/full_backup_$DATE.tar.gz"
    
    # Исключаем ненужные файлы
    tar -czf "$backup_file" \
        --exclude="logs/*.log.*" \
        --exclude="backups" \
        --exclude=".git" \
        --exclude="__pycache__" \
        --exclude="*.pyc" \
        -C "$PROJECT_DIR" .
    
    if [ $? -eq 0 ]; then
        log "Full project backup created: full_backup_$DATE.tar.gz"
        return 0
    else
        log_error "Failed to create full project backup"
        return 1
    fi
}

# Очистка старых бэкапов
cleanup_old_backups() {
    log "Cleaning up old backups (older than $RETENTION_DAYS days)..."
    
    # Удаляем старые бэкапы базы данных
    find "$BACKUP_DIR" -name "users_*.db" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true
    
    # Удаляем старые бэкапы конфигурации
    find "$BACKUP_DIR" -name "env_*" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true
    
    # Удаляем старые бэкапы логов
    find "$BACKUP_DIR" -name "logs_*.tar.gz" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true
    
    # Удаляем старые полные бэкапы
    find "$BACKUP_DIR" -name "full_backup_*.tar.gz" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true
    
    log "Old backups cleanup completed"
}

# Проверка места на диске
check_disk_space() {
    local available_space=$(df "$BACKUP_DIR" | tail -1 | awk '{print $4}')
    local required_space=100  # MB
    
    if [ $available_space -lt $required_space ]; then
        log_error "Insufficient disk space for backup (available: ${available_space}KB, required: ${required_space}MB)"
        notify_admin "❌ ОШИБКА: Недостаточно места для бэкапа"
        return 1
    fi
    
    return 0
}

# Создание отчета о бэкапе
create_backup_report() {
    local report_file="$BACKUP_DIR/backup_report_$DATE.txt"
    
    {
        echo "VPN Bot Backup Report - $(date)"
        echo "=================================="
        echo
        echo "Backup created: $DATE"
        echo "Backup directory: $BACKUP_DIR"
        echo
        echo "Files backed up:"
        ls -la "$BACKUP_DIR" | grep "$DATE" || echo "No files found"
        echo
        echo "Disk usage:"
        df -h "$BACKUP_DIR"
        echo
        echo "Backup completed successfully"
    } > "$report_file"
    
    log "Backup report created: backup_report_$DATE.txt"
}

# Основная функция бэкапа
main() {
    log "Starting VPN Bot backup process..."
    
    # Проверяем место на диске
    if ! check_disk_space; then
        exit 1
    fi
    
    # Создаем директорию бэкапа
    create_backup_dir
    
    # Выполняем бэкапы
    local backup_success=true
    
    backup_database || backup_success=false
    backup_config || backup_success=false
    backup_logs || backup_success=false
    backup_full_project || backup_success=false
    
    # Очищаем старые бэкапы
    cleanup_old_backups
    
    # Создаем отчет
    create_backup_report
    
    if [ "$backup_success" = true ]; then
        log "Backup completed successfully"
        notify_admin "✅ Бэкап VPN Bot выполнен успешно"
    else
        log_error "Backup completed with errors"
        notify_admin "⚠️ Бэкап VPN Bot выполнен с ошибками"
    fi
}

# Запуск
main "$@"
