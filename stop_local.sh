#!/bin/bash

# Скрипт для остановки бота и веб-интерфейса, запущенных через run_local.sh
# Автор: AI Assistant
# Дата: 2024-03-21

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Функции для логирования
log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Остановка бота
if [ -f "data/bot.pid" ]; then
    BOT_PID=$(cat data/bot.pid)
    log "Останавливаю бота (PID: $BOT_PID)..."
    kill $BOT_PID 2>/dev/null
    if [ $? -eq 0 ]; then
        log "Бот остановлен."
    else
        warn "Не удалось остановить бота. Возможно, процесс уже завершен."
    fi
    rm data/bot.pid
else
    warn "Файл data/bot.pid не найден. Бот, возможно, не запущен."
fi

# Остановка веб-интерфейса
if [ -f "data/web.pid" ]; then
    WEB_PID=$(cat data/web.pid)
    log "Останавливаю веб-интерфейс (PID: $WEB_PID)..."
    kill $WEB_PID 2>/dev/null
    if [ $? -eq 0 ]; then
        log "Веб-интерфейс остановлен."
    else
        warn "Не удалось остановить веб-интерфейс. Возможно, процесс уже завершен."
    fi
    rm data/web.pid
else
    warn "Файл data/web.pid не найден. Веб-интерфейс, возможно, не запущен."
fi

log "Все процессы остановлены." 