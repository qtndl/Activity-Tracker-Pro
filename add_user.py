import asyncio
from datetime import datetime
from database.database import AsyncSessionLocal, init_db
from database.models import Employee
from sqlalchemy import select

TELEGRAM_ID = 896737668
TELEGRAM_USERNAME = "admin"
FULL_NAME = "Лео"
IS_ADMIN = True

async def add_user():
    await init_db()
    async with AsyncSessionLocal() as session:
        # Проверяем существование пользователя
        result = await session.execute(
            select(Employee).where(Employee.telegram_id == TELEGRAM_ID)
        )
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            print(f"Пользователь с таким Telegram ID уже существует!")
            print(f"ID: {existing_user.id}")
            print(f"Имя: {existing_user.full_name}")
            print(f"Админ: {existing_user.is_admin}")
            print(f"Активен: {existing_user.is_active}")
            return

        # Создаем нового пользователя
        user = Employee(
            telegram_id=TELEGRAM_ID,
            telegram_username=TELEGRAM_USERNAME,
            full_name=FULL_NAME,
            is_active=True,
            is_admin=IS_ADMIN,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        session.add(user)
        await session.commit()
        print(f"Пользователь {FULL_NAME} добавлен!")

if __name__ == "__main__":
    asyncio.run(add_user()) 