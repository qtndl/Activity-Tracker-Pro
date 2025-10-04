#!/usr/bin/env python3
"""Простой скрипт инициализации базы данных"""

import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from database.models import Base, Employee, SystemSettings
from sqlalchemy import select

# Простые настройки без pydantic
DATABASE_URL = "postgresql+asyncpg://bot:Hesoyam123@localhost:5432/activity_db"

# Создаем движок и сессию
engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def init_database():
    """Инициализация базы данных"""
    print("Создание таблиц...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Таблицы созданы")

async def create_admin():
    """Создание администратора"""
    async with AsyncSessionLocal() as session:
        # Проверяем, есть ли уже админ с правильным ID
        result = await session.execute(
            select(Employee).where(Employee.telegram_id == 410916774)
        )
        admin = result.scalar_one_or_none()
        
        if not admin:
            admin = Employee(
                telegram_id=410916774,  # Ваш правильный Telegram ID
                telegram_username="kutin_dl",
                full_name="Администратор",
                is_admin=True,
                is_active=True
            )
            session.add(admin)
            await session.commit()
            print(f"✅ Создан администратор с Telegram ID: {admin.telegram_id}")
        else:
            # Убеждаемся, что админ активен
            admin.is_active = True
            await session.commit()
            print("ℹ️ Администратор уже существует")

async def create_default_settings():
    """Создание дефолтных настроек системы"""
    async with AsyncSessionLocal() as session:
        default_settings = [
            ("notification_delay_1", "15"),  # Первое уведомление через 15 минут
            ("notification_delay_2", "30"),  # Второе уведомление через 30 минут  
            ("notification_delay_3", "60"),  # Третье уведомление через 60 минут
            ("notifications_enabled", "true"),  # Уведомления включены
            ("daily_reports_enabled", "true"),  # Ежедневные отчеты включены
            ("daily_reports_time", "18:00"),  # Время отправки ежедневных отчетов
        ]
        
        for key, value in default_settings:
            # Проверяем, есть ли уже такая настройка
            result = await session.execute(
                select(SystemSettings).where(SystemSettings.key == key)
            )
            setting = result.scalar_one_or_none()
            
            if not setting:
                setting = SystemSettings(key=key, value=value)
                session.add(setting)
                print(f"✅ Создана настройка: {key} = {value}")
            else:
                print(f"ℹ️ Настройка {key} уже существует: {setting.value}")
        
        await session.commit()

async def main():
    await init_database()
    await create_admin()
    await create_default_settings()
    print("🎉 Инициализация завершена!")

if __name__ == "__main__":
    asyncio.run(main()) 