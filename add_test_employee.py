#!/usr/bin/env python3
"""Добавление тестового сотрудника"""

import asyncio
from database.database import AsyncSessionLocal
from database.models import Employee
from datetime import datetime

async def add_employee():
    async with AsyncSessionLocal() as session:
        employee = Employee(
            telegram_id=123456789,
            telegram_username='testuser',
            full_name='Тестовый Сотрудник',
            is_active=True,
            is_admin=False
        )
        session.add(employee)
        await session.commit()
        print('✅ Добавлен тестовый сотрудник')

if __name__ == "__main__":
    asyncio.run(add_employee()) 