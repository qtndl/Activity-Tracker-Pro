#!/usr/bin/env python3
"""Простой запуск веб-сервера"""

import os
import uvicorn

# Устанавливаем переменные окружения напрямую
os.environ["BOT_TOKEN"] = "8110382002:AAHuWex2O-QvW7ElqyOMu1ZHJEGiS8dSGmE"
os.environ["ADMIN_CHAT_ID"] = "896737668"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./employee_tracker.db"
os.environ["SECRET_KEY"] = "super-secret-key-change-in-production-2024"
os.environ["ALGORITHM"] = "HS256"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "43200"
os.environ["GOOGLE_SHEETS_ENABLED"] = "false"
os.environ["RESPONSE_TIME_WARNING_1"] = "15"
os.environ["RESPONSE_TIME_WARNING_2"] = "30"
os.environ["RESPONSE_TIME_WARNING_3"] = "60"
os.environ["WEB_HOST"] = "0.0.0.0"
os.environ["WEB_PORT"] = "8000"

if __name__ == "__main__":
    print("🚀 Запуск веб-сервера на http://localhost:8000")
    uvicorn.run(
        "web.main:app",  # Используем строку импорта
        host="0.0.0.0",
        port=8000,
        reload=False  # Отключаем reload для простоты
    ) 