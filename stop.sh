#!/bin/bash

echo "🛑 Остановка Telegram Bot Employee Tracker"
echo "=========================================="

# Остановка dev версии
docker-compose -f docker-compose.dev.yml down

echo "✅ Сервисы остановлены!" 