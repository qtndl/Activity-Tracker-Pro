#!/usr/bin/env python3
"""Миграция базы данных для умной логики"""

import os
import sqlite3
from datetime import datetime

# Устанавливаем переменные окружения
os.environ["BOT_TOKEN"] = "8110382002:AAHuWex2O-QvW7ElqyOMu1ZHJEGiS8dSGmE"
os.environ["ADMIN_CHAT_ID"] = "896737668"

def migrate_database():
    """Обновляет базу данных для поддержки умной логики"""
    
    print("🔧 Начинаем миграцию базы данных...")
    
    conn = sqlite3.connect('employee_tracker.db')
    cursor = conn.cursor()
    
    try:
        # Добавляем новые поля в таблицу messages
        print("📝 Добавляем новые поля в таблицу messages...")
        
        # Проверяем и добавляем client_telegram_id
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN client_telegram_id BIGINT")
            print("   ✅ Добавлено поле client_telegram_id")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print("   ⚠️ Поле client_telegram_id уже существует")
            else:
                raise
        
        # Проверяем и добавляем addressed_to_employee_id
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN addressed_to_employee_id INTEGER")
            cursor.execute("CREATE INDEX ix_messages_addressed_to_employee_id ON messages (addressed_to_employee_id)")
            print("   ✅ Добавлено поле addressed_to_employee_id")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e) or "already exists" in str(e):
                print("   ⚠️ Поле addressed_to_employee_id уже существует")
            else:
                raise
        
        # Проверяем и добавляем is_addressed_to_specific
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN is_addressed_to_specific BOOLEAN DEFAULT 0")
            print("   ✅ Добавлено поле is_addressed_to_specific")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print("   ⚠️ Поле is_addressed_to_specific уже существует")
            else:
                raise
        
        # Проверяем и добавляем reply_to_message_id
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN reply_to_message_id BIGINT")
            print("   ✅ Добавлено поле reply_to_message_id")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print("   ⚠️ Поле reply_to_message_id уже существует")
            else:
                raise
        
        # Проверяем и добавляем message_type
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN message_type VARCHAR DEFAULT 'client'")
            print("   ✅ Добавлено поле message_type")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print("   ⚠️ Поле message_type уже существует")
            else:
                raise
        
        # Создаем таблицу chat_employees
        print("👥 Создаем таблицу chat_employees...")
        try:
            cursor.execute("""
                CREATE TABLE chat_employees (
                    id INTEGER NOT NULL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    employee_id INTEGER NOT NULL,
                    is_active_in_chat BOOLEAN DEFAULT 1,
                    last_seen_at DATETIME NOT NULL,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(employee_id) REFERENCES employees (id)
                )
            """)
            cursor.execute("CREATE INDEX ix_chat_employees_id ON chat_employees (id)")
            cursor.execute("CREATE INDEX ix_chat_employees_chat_id ON chat_employees (chat_id)")
            cursor.execute("CREATE INDEX ix_chat_employees_employee_id ON chat_employees (employee_id)")
            print("   ✅ Таблица chat_employees создана")
        except sqlite3.OperationalError as e:
            if "already exists" in str(e):
                print("   ⚠️ Таблица chat_employees уже существует")
            else:
                raise
        
        # Обновляем существующие записи в messages
        print("🔄 Обновляем существующие записи...")
        cursor.execute("UPDATE messages SET message_type = 'client' WHERE message_type IS NULL")
        cursor.execute("UPDATE messages SET is_addressed_to_specific = 0 WHERE is_addressed_to_specific IS NULL")
        
        conn.commit()
        print("✅ Миграция завершена успешно!")
        
        # Проверяем результат
        cursor.execute("PRAGMA table_info(messages)")
        columns = cursor.fetchall()
        print("\n📋 Структура таблицы messages после миграции:")
        for col in columns:
            print(f"   {col[1]} ({col[2]})")
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chat_employees'")
        if cursor.fetchone():
            print("\n✅ Таблица chat_employees создана")
        else:
            print("\n❌ Таблица chat_employees НЕ создана")
    
    except Exception as e:
        print(f"❌ Ошибка при миграции: {e}")
        conn.rollback()
        raise
    
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_database() 