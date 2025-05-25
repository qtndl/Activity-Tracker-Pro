import asyncio
from datetime import datetime
from database.database import AsyncSessionLocal, init_db
from database.models import Employee

TELEGRAM_ID = 896737668
TELEGRAM_USERNAME = "admin"
FULL_NAME = "Администратор"
IS_ADMIN = True

async def add_user():
    await init_db()
    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            Employee.__table__.select().where(Employee.telegram_id == TELEGRAM_ID)
        )
        if existing.first():
            print("Пользователь с таким Telegram ID уже существует!")
            return

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