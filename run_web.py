#!/usr/bin/env python3
"""Простой запуск веб-сервера"""

import os
import uvicorn
import sys

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
    use_ssl = True
    if len(sys.argv) > 1 and sys.argv[1] == "--no-ssl":
        use_ssl = False

    print("🚀 Запуск веб-сервера...")
    if use_ssl:
        print("🌐 Сервер доступен по адресу: https://0.0.0.0:8000")
        uvicorn.run(
            "web.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            ssl_keyfile="certs/key.pem",
            ssl_certfile="certs/cert.pem"
        )
    else:
        print("🌐 Сервер доступен по адресу: http://0.0.0.0:8000 (без SSL)")
        uvicorn.run(
            "web.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True
        ) 