#!/usr/bin/env python3
"""Проверка состояния пользователя в базе данных"""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select
from database.models import Employee

# Настройки базы данных
DATABASE_URL = "sqlite+aiosqlite:///./employee_tracker.db"

# Создаем движок и сессию
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def check_user(telegram_id: int):
    """Проверка состояния пользователя"""
    async with AsyncSessionLocal() as session:
        # Найти всех пользователей с этим Telegram ID
        result = await session.execute(
            select(Employee).where(Employee.telegram_id == telegram_id)
        )
        users = result.scalars().all()
        
        print(f"🔍 Поиск пользователя с Telegram ID: {telegram_id}")
        print(f"📊 Найдено записей: {len(users)}")
        
        for i, user in enumerate(users, 1):
            print(f"\n👤 Запись #{i}:")
            print(f"  ID в базе: {user.id}")
            print(f"  Telegram ID: {user.telegram_id}")
            print(f"  Имя: {user.full_name}")
            print(f"  Username: {user.telegram_username}")
            print(f"  Активен: {'✅ Да' if user.is_active else '❌ Нет'}")
            print(f"  Администратор: {'✅ Да' if user.is_admin else '❌ Нет'}")
            print(f"  Создан: {user.created_at}")
            print(f"  Обновлен: {user.updated_at}")

async def fix_user(telegram_id: int):
    """Исправление состояния пользователя"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Employee).where(Employee.telegram_id == telegram_id)
        )
        user = result.scalars().first()
        
        if user:
            print(f"🔧 Исправляю пользователя {telegram_id}...")
            user.is_active = True
            user.is_admin = True
            await session.commit()
            print("✅ Пользователь исправлен!")
        else:
            print("❌ Пользователь не найден!")

async def main():
    telegram_id = 896737668
    
    print("=== ПРОВЕРКА СОСТОЯНИЯ ПОЛЬЗОВАТЕЛЯ ===")
    await check_user(telegram_id)
    
    print("\n=== ИСПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯ ===")
    await fix_user(telegram_id)
    
    print("\n=== ПОВТОРНАЯ ПРОВЕРКА ===")
    await check_user(telegram_id)

if __name__ == "__main__":
    asyncio.run(main()) 