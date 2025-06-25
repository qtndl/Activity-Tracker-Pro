#!/usr/bin/env python3
"""Скрипт инициализации базы данных"""

from database.database import init_db, init_deferred_message_simple
from database.models import Employee
from sqlalchemy.ext.asyncio import AsyncSession


async def main():
    print("Инициализация базы данных...")
    await init_db()
    await init_deferred_message_simple()
    print("✅ База данных и таблица deferred_messages_simple созданы")
    
    # Создаем первого администратора
    async with AsyncSession() as session:
        # Проверяем, есть ли уже админ
        admin = await session.get(Employee, 1)
        if not admin:
            admin = Employee(
                telegram_id=4867960619,  # Ваш Telegram ID
                telegram_username="kellax",  # Можете изменить
                full_name="Администратор",
                is_admin=True,
                is_active=True
            )
            session.add(admin)
            await session.commit()
            print(f"✅ Создан администратор с Telegram ID: {admin.telegram_id}")
        else:
            print("ℹ️ Администратор уже существует")
    
    print("🎉 Инициализация завершена!")


if __name__ == "__main__":
    import asyncio
    asyncio.run(init_db())
    asyncio.run(init_deferred_message_simple())
    print("База данных и таблица deferred_messages_simple инициализированы.")