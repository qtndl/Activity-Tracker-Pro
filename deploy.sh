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
        # === ДОБАВЛЯЮ ПОСЛЕ ЗАПУСКА КОНТЕЙНЕРОВ ===
        # Добавить админа, если переменная FIRST_ADMIN_ID задана
        if [ ! -z "$FIRST_ADMIN_ID" ]; then
          python3 add_user.py --admin --telegram_id $FIRST_ADMIN_ID
        fi
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

# Основная логика
case "${1:-deploy}" in
    "deploy")
        log "🚀 Начало развертывания Telegram Bot Employee Tracker"
        check_docker
        check_env
        create_dirs
        generate_ssl
        deploy
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