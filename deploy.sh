#!/bin/bash

# Цвета для логирования
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Функция логирования
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1"
}

# Проверка Docker
check_docker() {
    if ! command -v docker &> /dev/null; then
        error "Docker не установлен!"
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        error "Docker Compose не установлен!"
        exit 1
    fi
    
    log "Docker и Docker Compose установлены ✅"
}

# Проверка .env файла
check_env() {
    if [ ! -f .env ]; then
        error ".env файл не найден!"
        echo "Создайте .env файл на основе .env.example:"
        echo "cp .env.example .env"
        echo "Затем отредактируйте его с вашими настройками"
        exit 1
    fi
    
    # Проверка обязательных переменных
    required_vars=("BOT_TOKEN" "SECRET_KEY")
    for var in "${required_vars[@]}"; do
        if ! grep -q "^${var}=" .env; then
            error "Переменная $var не найдена в .env файле!"
            exit 1
        fi
        
        value=$(grep "^${var}=" .env | cut -d'=' -f2)
        if [[ $value == "your-"* ]] || [[ $value == "1234567890"* ]]; then
            error "Переменная $var содержит тестовое значение! Укажите реальное значение."
            exit 1
        fi
    done
    
    log "Файл .env проверен ✅"
}

# Создание необходимых директорий
create_dirs() {
    log "Создание директорий..."
    mkdir -p data logs ssl
    chmod 755 data logs
    log "Директории созданы ✅"
}

# Генерация SSL сертификатов (самоподписанных)
generate_ssl() {
    if [ ! -f ssl/cert.pem ] || [ ! -f ssl/key.pem ]; then
        warn "SSL сертификаты не найдены. Генерируем самоподписанные..."
        
        openssl req -x509 -newkey rsa:4096 -keyout ssl/key.pem -out ssl/cert.pem \
            -days 365 -nodes -subj "/C=RU/ST=State/L=City/O=Organization/CN=localhost"
        
        chmod 600 ssl/key.pem
        chmod 644 ssl/cert.pem
        
        warn "⚠️  Сгенерированы самоподписанные сертификаты для разработки!"
        warn "⚠️  Для продакшена используйте Let's Encrypt или другие сертификаты!"
    else
        log "SSL сертификаты найдены ✅"
    fi
}

# === ИНИЦИАЛИЗАЦИЯ БАЗЫ ЕСЛИ НУЖНО ===
init_db_if_needed() {
  if ! sqlite3 data/bot.db ".tables" | grep -q employees; then
    log "Таблица employees не найдена, инициализирую базу..."
    python3 simple_init.py
    log "База данных инициализирована."
  else
    log "Таблица employees найдена, инициализация не требуется."
  fi
}

# Сборка и запуск
deploy() {
    log "Остановка существующих контейнеров..."
    docker-compose down
    
    log "Сборка образов..."
    docker-compose build --no-cache
    
    log "Запуск сервисов..."
    if ! docker-compose up -d 2>&1 | tee /tmp/deploy.log; then
        # Проверяем, если проблема связана с rate limit
        if grep -q "toomanyrequests\|rate.limit" /tmp/deploy.log; then
            warn "❌ Обнаружена проблема с Docker Hub rate limit!"
            warn "🔄 Переключаемся на версию без nginx..."
            
            # Используем альтернативную версию
            log "Запуск без nginx (прямой доступ через порт 80)..."
            docker-compose -f docker-compose-no-nginx.yml down
            docker-compose -f docker-compose-no-nginx.yml up -d
            
            log "Ожидание запуска сервисов..."
            sleep 10
            
            # Проверка статуса альтернативной версии
            if docker-compose -f docker-compose-no-nginx.yml ps | grep -q "Up"; then
                log "🎉 Развертывание без nginx успешно завершено!"
                echo ""
                echo "🔗 Доступные сервисы:"
                echo "   📱 Telegram бот: @your_bot_name"
                echo "   🌐 Веб-интерфейс: http://localhost (порт 80)"
                echo "   🌐 Альтернативный доступ: http://localhost:8000"
                echo ""
                echo "⚠️  ВАЖНО: Nginx не запущен. SSL недоступен."
                echo "📝 Для добавления SSL позже используйте: docker login и ./deploy.sh"
                echo ""
                echo "📊 Статус контейнеров:"
                docker-compose -f docker-compose-no-nginx.yml ps
                echo ""
                echo "📝 Логи можно посмотреть командой:"
                echo "   docker-compose -f docker-compose-no-nginx.yml logs -f"
                return 0
            else
                error "Развертывание без nginx также не удалось!"
                echo "Логи ошибок:"
                docker-compose -f docker-compose-no-nginx.yml logs
                exit 1
            fi
        else
            error "Развертывание не удалось по неизвестной причине!"
            echo "Логи ошибок:"
            cat /tmp/deploy.log
            exit 1
        fi
    fi
    
    log "Ожидание запуска сервисов..."
    sleep 10
    
    # Проверка статуса обычной версии
    if docker-compose ps | grep -q "Up"; then
        log "🎉 Развертывание успешно завершено!"
        echo ""
        echo "🔗 Доступные сервисы:"
        echo "   📱 Telegram бот: @your_bot_name"
        echo "   🌐 Веб-интерфейс: https://localhost"
        echo "   🌐 Без SSL: http://localhost:8000"
        echo ""
        echo "📊 Статус контейнеров:"
        docker-compose ps
        echo ""
        echo "📝 Логи можно посмотреть командой:"
        echo "   docker-compose logs -f"
        echo ""
        log "Добавление администратора через add_user.py..."
        docker-compose exec web python /app/add_user.py || true
        # Добавить админа, если переменная FIRST_ADMIN_ID задана
        if [ ! -z "$FIRST_ADMIN_ID" ]; then
          if python3 add_user.py --admin --telegram_id $FIRST_ADMIN_ID; then
            log "✅ Админ с ID $FIRST_ADMIN_ID из .env создан успешно!"
          else
            error "❌ Не удалось создать админа с ID $FIRST_ADMIN_ID из .env!"
          fi
        fi
        print_db_info
        print_employees
    else
        error "Развертывание не удалось!"
        echo "Логи ошибок:"
        docker-compose logs
        exit 1
    fi
}

# Функция обновления
update() {
    log "Обновление приложения..."
    
    # Остановка сервисов
    docker-compose down
    
    # Пулл изменений (если это git репозиторий)
    if [ -d .git ]; then
        log "Получение обновлений из Git..."
        git pull
    fi
    
    # Пересборка и запуск
    docker-compose build --no-cache
    docker-compose up -d
    
    log "Обновление завершено ✅"
}

# Функция для просмотра логов
logs() {
    echo "📝 Логи приложения:"
    docker-compose logs -f --tail=100
}

# Функция для остановки
stop() {
    log "Остановка всех сервисов..."
    docker-compose down
    log "Сервисы остановлены ✅"
}

# === ДОБАВЛЯЮ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
print_db_info() {
    log "Проверка состояния базы данных..."
    if [ -f data/bot.db ]; then
        log "Файл базы данных найден: data/bot.db"
        python3 -c "import sqlite3; db=sqlite3.connect('data/bot.db'); print('Таблицы:', [r[0] for r in db.execute('SELECT name FROM sqlite_master WHERE type=\'table\'' )]); db.close()" || error "Не удалось прочитать таблицы из базы!"
    else
        warn "Файл базы данных data/bot.db не найден!"
    fi
}

print_employees() {
    log "Выводим список сотрудников из базы..."
    python3 -c "import sqlite3; db=sqlite3.connect('data/bot.db');
rows = db.execute('SELECT id, telegram_id, full_name, is_active, is_admin FROM employees').fetchall();
print('ID | Telegram ID | Имя | Активен | Админ');
for r in rows: print(f'{r[0]} | {r[1]} | {r[2]} | {"Да" if r[3] else "Нет"} | {"Да" if r[4] else "Нет"}');
db.close()" || warn "Не удалось вывести сотрудников из базы!"
}

# === ASCII-БАННЕР ===
print_banner() {
  echo -e "\n${BLUE}"
  echo "████████╗ ███████╗ ██████╗  ██████╗  ██████╗ ████████╗"
  echo "╚══██╔══╝ ██╔════╝██╔═══██╗██╔════╝ ██╔═══██╗╚══██╔══╝"
  echo "   ██║    █████╗  ██║   ██║██║  ███╗██║   ██║   ██║   "
  echo "   ██║    ██╔══╝  ██║   ██║██║   ██║██║   ██║   ██║   "
  echo "   ██║    ███████╗╚██████╔╝╚██████╔╝╚██████╔╝   ██║   "
  echo "   ╚═╝    ╚══════╝ ╚═════╝  ╚═════╝  ╚═════╝    ╚═╝   "
  echo -e "${NC}\n"
}

# === ПРОВЕРКА ВЕРСИЙ ===
check_versions() {
  log "Проверка версий Python, Docker и docker-compose..."
  python3 --version || warn "Python3 не найден!"
  docker --version || warn "Docker не найден!"
  docker-compose --version || warn "Docker Compose не найден!"
}

# === ПРОВЕРКА ПОРТОВ ===
check_ports() {
  log "Проверка занятости портов 80 и 8000..."
  for port in 80 8000; do
    if lsof -i :$port | grep LISTEN; then
      warn "Порт $port уже занят! Возможен конфликт."
    else
      log "Порт $port свободен."
    fi
  done
}

# === БЭКАП БАЗЫ ===
backup_db() {
  if [ -f data/bot.db ]; then
    ts=$(date +'%Y%m%d_%H%M%S')
    cp data/bot.db data/bot.db.bak_$ts
    log "Бэкап базы данных создан: data/bot.db.bak_$ts"
  fi
}

# === ЛОГИРОВАНИЕ ВРЕМЕНИ ===
timer_start() {
  export TIMER_START=$(date +%s)
}
timer_end() {
  local TIMER_END=$(date +%s)
  local DIFF=$((TIMER_END - TIMER_START))
  log "⏱️ Этап занял $DIFF секунд."
}

# === ВЫВОД ПОСЛЕДНИХ ЛОГОВ ПРИ ОШИБКЕ ===
print_last_logs() {
  echo "\nПоследние 30 строк логов контейнеров:\n"
  docker-compose logs --tail=30
}

# === HEALTHCHECK WEB ===
healthcheck_web() {
  # Получаем адрес и порт из .env или переменных окружения
  WEB_HOST=${WEB_HOST:-$(grep -E '^WEB_HOST=' .env | cut -d'=' -f2 | tr -d '"' | tr -d "'")}
  WEB_PORT=${WEB_PORT:-$(grep -E '^WEB_PORT=' .env | cut -d'=' -f2 | tr -d '"' | tr -d "'")}
  if [ -z "$WEB_HOST" ]; then WEB_HOST="localhost"; fi
  if [ -z "$WEB_PORT" ]; then WEB_PORT=8000; fi
  log "Проверка доступности web-интерфейса ($WEB_HOST:$WEB_PORT)..."
  if curl -sSf http://$WEB_HOST:$WEB_PORT/docs > /dev/null; then
    log "✅ Web-интерфейс доступен (http://$WEB_HOST:$WEB_PORT/docs)"
  else
    error "❌ Web-интерфейс НЕ доступен по адресу http://$WEB_HOST:$WEB_PORT/docs!"
  fi
}

# === DOCKER STATS ===
print_docker_stats() {
  log "Статистика по ресурсам контейнеров (docker stats, 5 сек)..."
  docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"
}

# === ВЫВОД ОШИБОК ИЗ ЛОГОВ WEB/BOT ===
print_last_errors() {
  log "Последние ошибки из логов web:"
  docker-compose logs web | grep -iE 'error|exception|traceback' | tail -n 10 || log "Ошибок не найдено."
  log "Последние ошибки из логов bot:"
  docker-compose logs bot | grep -iE 'error|exception|traceback' | tail -n 10 || log "Ошибок не найдено."
}

# === СРАВНЕНИЕ ХЭША БАЗЫ ДО И ПОСЛЕ ===
md5_before=""
md5_after=""
md5sum_db_before() {
  if [ -f data/bot.db ]; then
    md5_before=$(md5sum data/bot.db | awk '{print $1}')
    log "MD5 базы до деплоя: $md5_before"
  fi
}
md5sum_db_after() {
  if [ -f data/bot.db ]; then
    md5_after=$(md5sum data/bot.db | awk '{print $1}')
    log "MD5 базы после деплоя: $md5_after"
    if [ "$md5_before" != "" ] && [ "$md5_after" != "" ]; then
      if [ "$md5_before" = "$md5_after" ]; then
        log "База данных не изменилась."
      else
        warn "База данных изменилась!"
      fi
    fi
  fi
}

# Основная логика
case "${1:-deploy}" in
    "deploy")
        print_banner
        timer_start
        log "🚀 Начало развертывания Telegram Bot Employee Tracker"
        check_versions
        check_ports
        check_docker
        check_env
        create_dirs
        md5sum_db_before
        backup_db
        generate_ssl
        init_db_if_needed
        deploy || { print_last_logs; print_last_errors; exit 1; }
        timer_end
        md5sum_db_after
        healthcheck_web
        print_docker_stats
        print_last_errors
        ;;
    "update")
        log "🔄 Обновление приложения"
        update
        ;;
    "logs")
        logs
        ;;
    "stop")
        stop
        ;;
    "restart")
        stop
        sleep 3
        deploy
        ;;
    *)
        echo "Использование: $0 {deploy|update|logs|stop|restart}"
        echo ""
        echo "Команды:"
        echo "  deploy  - Первичное развертывание (по умолчанию)"
        echo "  update  - Обновление приложения"
        echo "  logs    - Просмотр логов"
        echo "  stop    - Остановка сервисов"
        echo "  restart - Перезапуск сервисов"
        exit 1
        ;;
esac 