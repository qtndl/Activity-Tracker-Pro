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
        columns = c.fetchall()
        found = False
        for col in columns:
            if col[1] == "from_user_id" and col[3] == 0:
                print(f"{DB_PATH}: from_user_id уже nullable, миграция не требуется.")
                found = True
                break
        if found:
            conn.close()
            continue
        if not columns:
            print(f"{DB_PATH}: deferred_messages_simple не найдена, пропускаем.")
            conn.close()
            continue
        print(f"{DB_PATH}: Мигрируем: делаем from_user_id nullable...")
        c.execute("ALTER TABLE deferred_messages_simple RENAME TO deferred_messages_simple_old")
        c.execute("""
        CREATE TABLE deferred_messages_simple (
            id INTEGER PRIMARY KEY,
            from_user_id BIGINT,
            from_username VARCHAR,
            text TEXT,
            date DATETIME NOT NULL,
            is_active BOOLEAN,
            created_at DATETIME
        )
        """)
        c.execute("""
        INSERT INTO deferred_messages_simple (id, from_user_id, from_username, text, date, is_active, created_at)
        SELECT id, from_user_id, from_username, text, date, is_active, created_at FROM deferred_messages_simple_old
        """)
        c.execute("DROP TABLE deferred_messages_simple_old")
        conn.commit()
        print(f"{DB_PATH}: Миграция завершена: from_user_id теперь nullable.")
    except Exception as e:
        print(f"{DB_PATH}: Ошибка миграции: {e}")
    finally:
        conn.close()
