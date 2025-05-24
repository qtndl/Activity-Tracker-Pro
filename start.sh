#!/bin/bash

echo "🚀 Быстрый запуск Telegram Bot Employee Tracker"
echo "================================================="

# Проверка .env файла
if [ ! -f .env ]; then
    echo "❌ .env файл не найден!"
    echo "Создайте его на основе .env.example:"
    echo "cp .env.example .env"
    exit 1
fi

# Создание директорий
mkdir -p data logs ssl

echo "🐳 Запуск в Docker (режим разработки)..."

# Запуск без nginx
docker-compose -f docker-compose.dev.yml up -d

echo ""
echo "✅ Сервисы запущены!"
echo ""
echo "🔗 Доступные сервисы:"
echo "   🌐 Веб-интерфейс: http://localhost:8000"
echo "   📱 Telegram бот: проверьте ваш бот"
echo ""
echo "📝 Команды управления:"
echo "   ./start.sh        - запуск"
echo "   ./stop.sh         - остановка"
echo "   ./logs.sh         - просмотр логов"
echo "   ./deploy.sh       - полное развертывание с SSL"
echo ""
echo "📊 Статус контейнеров:"
docker-compose -f docker-compose.dev.yml ps 