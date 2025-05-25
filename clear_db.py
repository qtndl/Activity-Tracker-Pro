import asyncio
from sqlalchemy import text
from database.database import AsyncSessionLocal

async def clear_database():
    """Очистка всех таблиц кроме employees"""
    async with AsyncSessionLocal() as session:
        try:
            # Список таблиц для очистки
            tables = [
                'messages',
                'notifications'
            ]
            
            # Отключаем проверку внешних ключей для SQLite
            await session.execute(text('PRAGMA foreign_keys = OFF'))
            
            # Очищаем каждую таблицу
            for table in tables:
                await session.execute(text(f'DELETE FROM {table}'))
                print(f'✅ Таблица {table} очищена')
            
            # Включаем проверку внешних ключей обратно
            await session.execute(text('PRAGMA foreign_keys = ON'))
            
            # Подтверждаем изменения
            await session.commit()
            print('✅ База данных успешно очищена')
            
        except Exception as e:
            await session.rollback()
            print(f'❌ Ошибка при очистке базы данных: {str(e)}')
            raise

if __name__ == "__main__":
    asyncio.run(clear_database()) 