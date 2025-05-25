#!/usr/bin/env python3
"""Простой запуск веб-сервера"""

import os
import uvicorn

# Проверка обязательных переменных окружения
required_vars = ["BOT_TOKEN", "SECRET_KEY"]
missing_vars = []

for var in required_vars:
    if not os.getenv(var):
        missing_vars.append(var)

if missing_vars:
    print("❌ Отсутствуют обязательные переменные окружения:")
    for var in missing_vars:
        print(f"   - {var}")
    print("\nСоздайте .env файл на основе .env.example")
    exit(1)

# Импорт приложения
from web.main import app

if __name__ == "__main__":
    print("🚀 Запуск веб-сервера...")
    
    # Получаем настройки из переменных окружения
    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8000"))
    
    print(f"🌐 Сервер доступен по адресу: https://{host}:{port}")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=False,
        ssl_keyfile="certs/privkey.pem",
        ssl_certfile="certs/fullchain.pem"
    ) 