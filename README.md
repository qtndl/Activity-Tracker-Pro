# Activity-Tracker-Pro

## Описание

Activity-Tracker-Pro — это система для отслеживания активности сотрудников и обработки сообщений клиентов через Telegram-бота и веб-интерфейс администратора. Проект поддерживает автоматические уведомления, аналитику, отчёты и интеграцию с Google Sheets.

---

## Быстрый старт

1. **Клонируйте репозиторий:**
   ```sh
   git clone <repo_url>
   cd Activity-Tracker-Pro
   ```
2. **Создайте и настройте файл `.env`** (пример ниже).
3. **Установите Python 3.11+ и pip3**
4. **Запустите локально:**
   ```sh
   ./run_local.sh
   ```
5. **Откройте веб-интерфейс:**
   [http://localhost:8000](http://localhost:8000)

---

## Переменные окружения (`.env`)

Пример:
```
DATABASE_URL=sqlite+aiosqlite:///./bot.db
BOT_TOKEN=ВАШ_ТОКЕН_ТГ_БОТА
FIRST_ADMIN_ID=123456789
GOOGLE_SHEETS_ENABLED=false
GOOGLE_SHEETS_CREDENTIALS_FILE=credentials.json
GOOGLE_SHEETS_SPREADSHEET_ID=...
GOOGLE_SHEETS_WORKSHEET_NAME=...
```

- **DATABASE_URL** — строка подключения к БД (по умолчанию SQLite).
- **BOT_TOKEN** — токен Telegram-бота.
- **FIRST_ADMIN_ID** — Telegram ID первого администратора.
- **GOOGLE_SHEETS_...** — параметры для интеграции с Google Sheets (опционально).

---

## Основные команды

- `./run_local.sh` — запуск бота и веб-интерфейса
- `./stop_local.sh` — остановка всех процессов
- `tail -f logs/bot.log` — просмотр логов бота
- `tail -f logs/web.log` — просмотр логов веб-интерфейса

---

## Структура проекта

- `bot/` — Telegram-бот, логика обработки сообщений, уведомления
- `web/` — веб-интерфейс администратора (FastAPI, Jinja2)
- `database/` — инициализация и работа с БД
- `config/` — конфигурация и переменные окружения
- `logs/` — логи работы
- `run_local.sh`, `stop_local.sh` — скрипты запуска/остановки

---

## Поддержка и FAQ

- Если возникли ошибки при запуске — проверьте наличие Python 3.11+, pip3, корректность `.env` и зависимостей (`requirements.txt`).
- Для Telegram-авторизации используйте кнопку "Войти через Telegram" на главной странице веб-интерфейса.
- Для интеграции с Google Sheets требуется сервисный аккаунт и файл `credentials.json`.

---

## Контакты

По вопросам и багам: [Telegram](https://t.me/kellax) 