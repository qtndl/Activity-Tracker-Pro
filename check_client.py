#!/usr/bin/env python3
"""Проверка конкретного клиента"""

import asyncio
from database.database import AsyncSessionLocal
from database.models import Employee, Message
from sqlalchemy import select

async def check_client():
    client_id = 442338328
    
    async with AsyncSessionLocal() as db:
        print(f"🔍 ПРОВЕРКА КЛИЕНТА ID: {client_id}\n")
        
        # 1. Проверяем не является ли клиент сотрудником
        result = await db.execute(
            select(Employee).where(Employee.telegram_id == client_id)
        )
        employee = result.scalar_one_or_none()
        
        if employee:
            print(f"❌ ПРОБЛЕМА НАЙДЕНА!")
            print(f"   Клиент {client_id} ЯВЛЯЕТСЯ сотрудником:")
            print(f"   📛 Имя: {employee.full_name}")
            print(f"   👤 Username: @{employee.telegram_username}")
            print(f"   ✅ Активен: {employee.is_active}")
            print(f"   👑 Админ: {employee.is_admin}")
            print(f"\n💡 РЕШЕНИЕ: Удалите этого сотрудника из системы или деактивируйте")
        else:
            print(f"✅ Клиент {client_id} НЕ является сотрудником - это правильно!")
        
        # 2. Проверяем сообщения от этого клиента
        result = await db.execute(
            select(Message).where(Message.client_telegram_id == client_id)
            .order_by(Message.received_at.desc())
        )
        messages = result.scalars().all()
        
        print(f"\n📨 СООБЩЕНИЯ ОТ КЛИЕНТА {client_id}:")
        if messages:
            for msg in messages[:5]:  # Показываем последние 5
                print(f"   🔸 ID: {msg.id}")
                print(f"   ⏰ Время: {msg.received_at}")
                print(f"   💬 Текст: {msg.message_text[:50] if msg.message_text else 'Нет текста'}...")
                print(f"   👤 Для сотрудника: {msg.employee_id}")
                print(f"   ✅ Отвечено: {'Да' if msg.responded_at else 'Нет'}")
                print("   ---")
        else:
            print(f"   ❌ НЕТ СООБЩЕНИЙ от клиента {client_id}")
            print(f"   💡 Это означает что бот НЕ ВИДИТ сообщения!")
            print(f"\n🔧 ВОЗМОЖНЫЕ ПРИЧИНЫ:")
            print(f"   1. Бот НЕ администратор в группе")
            print(f"   2. У бота нет права 'читать все сообщения'")
            print(f"   3. Бот не запущен или есть ошибки")
            print(f"   4. Клиент писал не в ту группу где есть бот")
        
        # 3. Показываем общее количество сообщений в системе
        result = await db.execute(select(Message))
        all_messages = result.scalars().all()
        print(f"\n📊 ВСЕГО СООБЩЕНИЙ В СИСТЕМЕ: {len(all_messages)}")
        
        if len(all_messages) == 0:
            print(f"❗ ПРОБЛЕМА: В системе вообще нет сообщений!")
            print(f"   Это означает что бот не записывает НИКАКИЕ сообщения")

if __name__ == "__main__":
    asyncio.run(check_client()) 