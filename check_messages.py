#!/usr/bin/env python3
"""Проверка сообщений в базе данных"""

import asyncio
from database.database import AsyncSessionLocal
from database.models import Message, Employee
from sqlalchemy import select

async def check_messages():
    """Проверка сообщений в базе"""
    async with AsyncSessionLocal() as session:
        # Проверяем сотрудников
        result = await session.execute(select(Employee))
        employees = result.scalars().all()
        print("\n👥 Сотрудники в базе:")
        for emp in employees:
            print(f"ID: {emp.id}, Telegram ID: {emp.telegram_id}, Имя: {emp.full_name}")
        
        # Проверяем сообщения
        result = await session.execute(select(Message))
        messages = result.scalars().all()
        print(f"\n📨 Всего сообщений: {len(messages)}")
        
        if messages:
            print("\n📊 Статистика по сообщениям:")
            for msg in messages:
                print(f"ID: {msg.id}, Сотрудник: {msg.employee_id}, "
                      f"Тип: {msg.message_type}, "
                      f"Получено: {msg.received_at}, "
                      f"Отвечено: {msg.responded_at}, "
                      f"Время ответа: {msg.response_time_minutes} мин")
        else:
            print("\n❌ Сообщений в базе нет!")
            print("\n💡 Что делать:")
            print("1. Добавьте бота в группу")
            print("2. Дайте боту права администратора")
            print("3. Пусть кто-то напишет сообщение в группу")
            print("4. Ответьте на это сообщение (reply)")

if __name__ == "__main__":
    asyncio.run(check_messages()) 