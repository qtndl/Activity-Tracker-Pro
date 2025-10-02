import sqlite3
import os

DB_PATHS = [
    "bot.db"
]

def get_columns(c, table):
    c.execute(f"PRAGMA table_info({table})")
    # returns list of dicts: {cid, name, type, notnull, dflt_value, pk}
    rows = c.fetchall()
    return rows

for DB_PATH in DB_PATHS:
    if not os.path.exists(DB_PATH):
        print(f"{DB_PATH}: файл не найден, пропускаем.")
        continue

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    c = conn.cursor()

    try:
        # Проверяем наличие таблицы
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='deferred_messages_simple'")
        if not c.fetchone():
            print(f"{DB_PATH}: deferred_messages_simple не найдена, пропускаем.")
            conn.close()
            continue

        columns = get_columns(c, "deferred_messages_simple")
        col_names = {col[1] for col in columns}
        col_by_name = {col[1]: col for col in columns}

        # Нужно ли пересоздавать таблицу (если from_user_id NOT NULL)
        need_recreate = False
        if "from_user_id" in col_by_name:
            notnull = col_by_name["from_user_id"][3]  # PRAGMA table_info: 3 = notnull flag
            if notnull == 1:
                need_recreate = True

        # Если пересоздавать не нужно, просто добавим недостающие колонки
        if not need_recreate:
            # Добавим original_message_id если нет
            if "original_message_id" not in col_names:
                print(f"{DB_PATH}: Добавляем колонку original_message_id...")
                c.execute("ALTER TABLE deferred_messages_simple ADD COLUMN original_message_id INTEGER")
                # Индекс (по желанию)
                c.execute("CREATE INDEX IF NOT EXISTS ix_deferred_messages_simple_original_message_id ON deferred_messages_simple(original_message_id)")
                conn.commit()
                print(f"{DB_PATH}: Колонка original_message_id добавлена.")

            # Также убедимся, что присутствуют остальные новые колонки
            for new_col, col_type in [
                ("client_telegram_id", "BIGINT"),
                ("employee_id", "INTEGER"),
                ("chat_id", "BIGINT"),
            ]:
                if new_col not in col_names:
                    print(f"{DB_PATH}: Добавляем колонку {new_col}...")
                    c.execute(f"ALTER TABLE deferred_messages_simple ADD COLUMN {new_col} {col_type}")
                    conn.commit()

            print(f"{DB_PATH}: Миграция завершена (без пересоздания таблицы).")
            conn.close()
            continue

        # Пересоздаем таблицу: сохраним все актуальные колонки и добавим original_message_id
        print(f"{DB_PATH}: Пересоздаем таблицу (делаем from_user_id nullable и добавляем original_message_id)...")
        c.execute("ALTER TABLE deferred_messages_simple RENAME TO deferred_messages_simple_old")

        # Желаемая схема (включая новые колонки)
        create_sql = """
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
            chat_id BIGINT,
            original_message_id INTEGER,
            FOREIGN KEY(original_message_id) REFERENCES messages(id) ON DELETE SET NULL
        )
        """
        c.execute(create_sql)

        # Список колонок, которые реально есть в старой таблице (пересекаем с новой схемой)
        new_cols_order = [
            "id",
            "from_user_id",
            "from_username",
            "text",
            "date",
            "is_active",
            "created_at",
            "client_telegram_id",
            "employee_id",
            "chat_id",
            # original_message_id не было — вставим NULL
        ]
        old_existing_cols = [col for col in new_cols_order if col in col_names]

        # Формируем SQL на перенос данных
        insert_cols = ", ".join(old_existing_cols)
        select_cols = ", ".join(old_existing_cols)
        if insert_cols:
            c.execute(f"""
                INSERT INTO deferred_messages_simple ({insert_cols})
                SELECT {select_cols}
                FROM deferred_messages_simple_old
            """)
        else:
            print(f"{DB_PATH}: В старой таблице не найдено известных колонок, перенос пропущен.")

        # Индексы (по желанию)
        c.execute("CREATE INDEX IF NOT EXISTS ix_deferred_messages_simple_original_message_id ON deferred_messages_simple(original_message_id)")

        c.execute("DROP TABLE deferred_messages_simple_old")
        conn.commit()
        print(f"{DB_PATH}: Миграция завершена: from_user_id теперь nullable, original_message_id добавлен.")
    except Exception as e:
        print(f"{DB_PATH}: Ошибка миграции: {e}")
    finally:
        conn.close()