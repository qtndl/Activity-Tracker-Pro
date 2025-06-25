import sqlite3
import os

DB_PATHS = [
    "bot.db"
]

for DB_PATH in DB_PATHS:
    if not os.path.exists(DB_PATH):
        print(f"{DB_PATH}: файл не найден, пропускаем.")
        continue
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("PRAGMA table_info(deferred_messages_simple)")
        columns = [col[1] for col in c.fetchall()]
        need_migration = False
        for col in ["client_telegram_id", "employee_id", "chat_id"]:
            if col not in columns:
                need_migration = True
        if not need_migration:
            print(f"{DB_PATH}: все нужные поля уже есть, миграция не требуется.")
            conn.close()
            continue
        print(f"{DB_PATH}: Мигрируем: добавляем client_telegram_id, employee_id, chat_id...")
        c.execute("ALTER TABLE deferred_messages_simple RENAME TO deferred_messages_simple_old")
        c.execute("""
        CREATE TABLE deferred_messages_simple (
            id INTEGER PRIMARY KEY,
            from_user_id BIGINT,
            from_username VARCHAR,
            text TEXT,
            date DATETIME NOT NULL,
            is_active BOOLEAN,
            created_at DATETIME,
            client_telegram_id BIGINT,
            employee_id INTEGER,
            chat_id BIGINT
        )
        """)
        c.execute("""
        INSERT INTO deferred_messages_simple (id, from_user_id, from_username, text, date, is_active, created_at)
        SELECT id, from_user_id, from_username, text, date, is_active, created_at FROM deferred_messages_simple_old
        """)
        c.execute("DROP TABLE deferred_messages_simple_old")
        conn.commit()
        print(f"{DB_PATH}: Миграция завершена: новые поля добавлены.")
    except Exception as e:
        print(f"{DB_PATH}: Ошибка миграции: {e}")
    finally:
        conn.close()
