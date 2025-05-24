FROM python:3.11-slim

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Создаем пользователя для приложения (безопасность)
RUN useradd --create-home --shell /bin/bash tgbot

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файлы зависимостей
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код приложения
COPY . .

# Удаляем файлы с секретами (на всякий случай)
RUN rm -f .env credentials.json

# Создаем директории для данных
RUN mkdir -p /app/data /app/logs

# Меняем владельца файлов
RUN chown -R tgbot:tgbot /app

# Переключаемся на непривилегированного пользователя
USER tgbot

# Открываем порт для веб-приложения
EXPOSE 8000

# Команда по умолчанию
CMD ["python", "run_web.py"] 