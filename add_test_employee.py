#!/usr/bin/env python3
"""Добавление тестового сотрудника"""

import asyncio
from database.database import AsyncSessionLocal
from database.models import Employee
from datetime import datetime

async def add_test_employee():
    print("➕ ДОБАВЛЕНИЕ ТЕСТОВОГО СОТРУДНИКА\n")
    
    # Запрашиваем данные
    print("Введите данные для нового сотрудника:")
    telegram_id = input("🆔 Telegram ID: ")
    username = input("👤 Username (без @): ")
    full_name = input("📛 Полное имя: ")
    
    try:
        telegram_id = int(telegram_id)
        
        async with AsyncSessionLocal() as db:
            # Проверяем что такого сотрудника нет
            from sqlalchemy import select
            result = await db.execute(
                select(Employee).where(Employee.telegram_id == telegram_id)
            )
            existing = result.scalar_one_or_none()
            
            if existing:
                print(f"❌ Сотрудник с ID {telegram_id} уже существует!")
                return
            
            # Создаем нового сотрудника
            new_employee = Employee(
                telegram_id=telegram_id,
                telegram_username=username,
                full_name=full_name,
                is_active=True,
                is_admin=False,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            db.add(new_employee)
            await db.commit()
            await db.refresh(new_employee)
            
            print(f"✅ Сотрудник добавлен!")
            print(f"   ID: {new_employee.id}")
            print(f"   Telegram ID: {new_employee.telegram_id}")
            print(f"   Имя: {new_employee.full_name}")
            print(f"   Username: @{new_employee.telegram_username}")
            
            print(f"\n💡 Теперь если этот человек будет писать в чате:")
            print(f"   → Его сообщения НЕ будут считаться клиентскими")
            print(f"   → Уведомления НЕ будут создаваться")
            
    except ValueError:
        print("❌ Telegram ID должен быть числом!")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(add_test_employee()) 