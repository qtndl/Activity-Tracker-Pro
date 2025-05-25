"""
Миграция для добавления поля answered_by_employee_id в таблицу messages
"""
import asyncio
from sqlalchemy import text
from database.database import init_db, AsyncSessionLocal

async def add_answered_by_field():
    """Добавление поля answered_by_employee_id в таблицу messages"""
    await init_db()
    
    async with AsyncSessionLocal() as session:
        try:
            # Проверяем, существует ли уже поле
            result = await session.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'messages' 
                AND column_name = 'answered_by_employee_id'
            """))
            
            if result.fetchone():
                print("✅ Поле answered_by_employee_id уже существует")
                return
            
            # Добавляем новое поле
            await session.execute(text("""
                ALTER TABLE messages 
                ADD COLUMN answered_by_employee_id INTEGER
            """))
            
            # Добавляем внешний ключ
            await session.execute(text("""
                ALTER TABLE messages 
                ADD CONSTRAINT fk_messages_answered_by_employee 
                FOREIGN KEY (answered_by_employee_id) 
                REFERENCES employees(id)
            """))
            
            await session.commit()
            print("✅ Поле answered_by_employee_id успешно добавлено")
            
        except Exception as e:
            await session.rollback()
            print(f"❌ Ошибка миграции: {e}")
            # Если SQLite, то внешние ключи работают по-другому
            try:
                await session.execute(text("""
                    ALTER TABLE messages 
                    ADD COLUMN answered_by_employee_id INTEGER
                """))
                await session.commit()
                print("✅ Поле answered_by_employee_id добавлено (без FK для SQLite)")
            except Exception as e2:
                print(f"❌ Ошибка добавления поля: {e2}")

if __name__ == "__main__":
    asyncio.run(add_answered_by_field()) 