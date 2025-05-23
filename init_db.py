#!/usr/bin/env python3
"""Скрипт инициализации базы данных"""

import asyncio
from database.database import init_db, AsyncSessionLocal
from database.models import Employee


async def main():
    print("Инициализация базы данных...")
    await init_db()
    print("✅ База данных создана")
    
    # Создаем первого администратора
    async with AsyncSessionLocal() as session:
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
    asyncio.run(main()) 