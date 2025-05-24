#!/bin/bash

echo "📝 Логи Telegram Bot Employee Tracker"
echo "======================================"

# Показ логов dev версии
docker-compose -f docker-compose.dev.yml logs -f --tail=100 