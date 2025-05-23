"""
Скрипт для создания тестовых сообщений
"""
import asyncio
from datetime import datetime, timedelta
from database.database import AsyncSessionLocal
from database.models import Message, Employee
from sqlalchemy import select
import random

async def create_test_messages():
    async with AsyncSessionLocal() as session:
        # Получаем сотрудников
        result = await session.execute(select(Employee))
        employees = result.scalars().all()
        
        if not employees:
            print("❌ Нет сотрудников в базе")
            return
        
        print(f"📧 Создаём тестовые сообщения для {len(employees)} сотрудников...")
        
        # Создаём сообщения за последние 3 дня
        for days_ago in range(3):
            date = datetime.utcnow() - timedelta(days=days_ago)
            
            for employee in employees:
                # Случайное количество сообщений для каждого сотрудника
                num_messages = random.randint(3, 8)
                
                for i in range(num_messages):
                    # Время сообщения
                    msg_time = date.replace(
                        hour=random.randint(9, 18),
                        minute=random.randint(0, 59),
                        second=random.randint(0, 59)
                    )
                    
                    # Случайно определяем, отвечено ли на сообщение
                    is_responded = random.choice([True, True, True, False])  # 75% отвечено
                    
                    response_time = None
                    responded_at = None
                    
                    if is_responded:
                        # Случайное время ответа от 2 до 45 минут
                        response_time = random.uniform(2, 45)
                        responded_at = msg_time + timedelta(minutes=response_time)
                    
                    message = Message(
                        employee_id=employee.id,
                        chat_id=random.randint(100000, 999999),
                        message_id=random.randint(1000, 9999),
                        client_username=f"client_{random.randint(1, 100)}",
                        client_name=f"Клиент {random.randint(1, 100)}",
                        message_text=f"Тестовое сообщение #{i+1}",
                        message_type="client",
                        received_at=msg_time,
                        responded_at=responded_at,
                        response_time_minutes=response_time,
                        is_missed=not is_responded
                    )
                    
                    session.add(message)
                
                print(f"   📅 {date.date()} - {employee.full_name}: {num_messages} сообщений")
        
        await session.commit()
        print("✅ Тестовые сообщения созданы!")
        
        # Показываем итоги
        result = await session.execute(select(Message))
        all_messages = result.scalars().all()
        print(f"📊 Всего сообщений в базе: {len(all_messages)}")

if __name__ == "__main__":
    asyncio.run(create_test_messages()) 