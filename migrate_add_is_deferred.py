import sqlite3
import os

DB_PATH = os.getenv('DB_PATH', 'bot.db')

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Проверяем, есть ли уже поле is_deferred
c.execute("PRAGMA table_info(messages)")
columns = [row[1] for row in c.fetchall()]

if 'is_deferred' not in columns:
    print('Добавляю поле is_deferred в messages...')
    c.execute("ALTER TABLE messages ADD COLUMN is_deferred BOOLEAN DEFAULT 0")
    conn.commit()
    print('Поле is_deferred успешно добавлено.')
else:
    print('Поле is_deferred уже существует.')

conn.close() 