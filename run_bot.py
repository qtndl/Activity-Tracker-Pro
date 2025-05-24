#!/usr/bin/env python3
"""Простой запуск Telegram бота"""

import os
import asyncio

# Проверка переменных окружения
if not os.getenv("BOT_TOKEN"):
    print("❌ BOT_TOKEN не установлен в переменных окружения!")
    print("Создайте .env файл или установите переменную:")
    print("export BOT_TOKEN=your_bot_token_here")
    exit(1)

# Импорт основного модуля
from bot.main import main

if __name__ == "__main__":
    print("🚀 Запуск Telegram бота...")
    asyncio.run(main()) 