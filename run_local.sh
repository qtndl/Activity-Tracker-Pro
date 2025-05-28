#!/bin/bash

# Скрипт для запуска бота и веб-интерфейса без Docker
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

# Проверка наличия Python и pip
if ! command -v python3 &> /dev/null; then
    error "Python3 не установлен. Установите Python3 и попробуйте снова."
    exit 1
fi

if ! command -v pip3 &> /dev/null; then
    error "pip3 не установлен. Установите pip3 и попробуйте снова."
    exit 1
fi

# Проверка наличия виртуального окружения
if [ ! -d ".venv" ]; then
    log "Создаю виртуальное окружение..."
    python3 -m venv .venv
    if [ $? -ne 0 ]; then
        error "Не удалось создать виртуальное окружение."
        exit 1
    fi
fi

# Активация виртуального окружения
log "Активация виртуального окружения..."
source .venv/bin/activate

# Установка зависимостей
log "Установка зависимостей..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    error "Не удалось установить зависимости."
    exit 1
fi

# Проверка наличия файла .env
if [ ! -f ".env" ]; then
    error "Файл .env не найден. Создайте его на основе .env.example."
    exit 1
fi

# Проверка наличия директории data
if [ ! -d "data" ]; then
    log "Создаю директорию data..."
    mkdir -p data
fi

# Проверка наличия директории logs
if [ ! -d "logs" ]; then
    log "Создаю директорию logs..."
    mkdir -p logs
fi

# Инициализация базы данных, если она не существует
if [ ! -f "data/bot.db" ]; then
    log "Инициализация базы данных..."
    PYTHONPATH=$PYTHONPATH:$(pwd) python -m simple_init
    if [ $? -ne 0 ]; then
        error "Не удалось инициализировать базу данных."
        exit 1
    fi
fi

# Миграция: добавление поля is_deferred
log "Проверка и миграция поля is_deferred в messages..."
PYTHONPATH=$PYTHONPATH:$(pwd) python migrate_add_is_deferred.py

# Добавление админа из FIRST_ADMIN_ID
if [ -n "$FIRST_ADMIN_ID" ]; then
    log "Добавление админа из FIRST_ADMIN_ID..."
    PYTHONPATH=$PYTHONPATH:$(pwd) python -c "
import os
from database.database import AsyncSessionLocal
from database.models import Employee
from sqlalchemy import select
import asyncio

async def add_admin():
    async with AsyncSessionLocal() as session:
        # Проверяем, существует ли уже админ с таким telegram_id
        result = await session.execute(
            select(Employee).where(Employee.telegram_id == '$FIRST_ADMIN_ID')
        )
        existing_admin = result.scalar_one_or_none()
        
        if not existing_admin:
            # Создаем нового админа
            admin = Employee(
                telegram_id='$FIRST_ADMIN_ID',
                full_name='Администратор',
                is_admin=True,
                is_active=True
            )
            session.add(admin)
            await session.commit()
            print('Админ успешно добавлен')
        else:
            print('Админ уже существует')

asyncio.run(add_admin())
"
    if [ $? -ne 0 ]; then
        warn "Не удалось добавить админа из FIRST_ADMIN_ID"
    fi
fi

# Запуск бота в фоновом режиме
log "Запуск бота..."
PYTHONPATH=$PYTHONPATH:$(pwd) python -m bot.main > logs/bot.log 2>&1 &
BOT_PID=$!
echo $BOT_PID > data/bot.pid
log "Бот запущен с PID: $BOT_PID"
log "Логи бота: logs/bot.log"

# Запуск веб-интерфейса в фоновом режиме
log "Запуск веб-интерфейса..."
PYTHONPATH=$PYTHONPATH:$(pwd) python -m web.main > logs/web.log 2>&1 &
WEB_PID=$!
echo $WEB_PID > data/web.pid
log "Веб-интерфейс запущен с PID: $WEB_PID"
log "Логи веб-интерфейса: logs/web.log"

log "Бот и веб-интерфейс запущены в фоновом режиме."
log "Бот: PID $BOT_PID"
log "Веб-интерфейс: PID $WEB_PID"
log "Для остановки используйте: ./stop_local.sh"
log "Для просмотра логов используйте:"
log "  tail -f logs/bot.log    # логи бота"
log "  tail -f logs/web.log    # логи веб-интерфейса" 