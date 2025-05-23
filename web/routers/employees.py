from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_, func, desc
from datetime import datetime, timedelta
from pydantic import BaseModel

from database.database import get_db
from database.models import Employee, Message, EmployeeStatistics
from web.auth import get_current_user, get_current_admin

router = APIRouter()


class EmployeeCreate(BaseModel):
    telegram_id: int
    telegram_username: str
    full_name: str
    is_active: bool = True


class EmployeeUpdate(BaseModel):
    telegram_username: Optional[str] = None
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None


class EmployeeResponse(BaseModel):
    id: int
    telegram_id: int
    telegram_username: Optional[str] = None
    full_name: str
    is_active: Optional[bool] = True
    is_admin: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@router.get("/", response_model=List[EmployeeResponse])
async def get_employees(
    current_user: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Получить список всех сотрудников (только для админов)"""
    result = await db.execute(select(Employee))
    employees = result.scalars().all()
    return employees


@router.get("/me", response_model=EmployeeResponse)
async def get_my_profile(
    current_user: dict = Depends(get_current_user)
):
    """Получить профиль текущего пользователя"""
    return {
        "id": current_user.get('employee_id'),
        "telegram_id": current_user.get('telegram_id'),
        "telegram_username": current_user.get('telegram_username'),
        "full_name": current_user.get('full_name'),
        "is_active": current_user.get('is_active'),
        "is_admin": current_user.get('is_admin'),
        "created_at": current_user.get('created_at'),
        "updated_at": None
    }


@router.get("/{employee_id}", response_model=EmployeeResponse)
async def get_employee(
    employee_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Получить информацию о сотруднике"""
    # Обычные сотрудники могут видеть только свой профиль
    if not current_user.get('is_admin') and employee_id != current_user.get('employee_id'):
        raise HTTPException(status_code=403, detail="Недостаточно прав доступа")
    
    result = await db.execute(select(Employee).where(Employee.id == employee_id))
    employee = result.scalar_one_or_none()
    
    if not employee:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    
    return employee


@router.post("/", response_model=EmployeeResponse)
async def create_employee(
    employee_data: EmployeeCreate,
    current_user: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Создать нового сотрудника (только для админов)"""
    # Проверяем, что telegram_id уникален
    existing = await db.execute(
        select(Employee).where(Employee.telegram_id == employee_data.telegram_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="Сотрудник с таким Telegram ID уже существует"
        )
    
    # Создаем нового сотрудника
    employee = Employee(
        telegram_id=employee_data.telegram_id,
        telegram_username=employee_data.telegram_username,
        full_name=employee_data.full_name,
        is_active=employee_data.is_active,
        is_admin=False  # По умолчанию не админ
    )
    
    db.add(employee)
    await db.commit()
    await db.refresh(employee)
    
    return employee


@router.put("/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    employee_id: int,
    employee_data: EmployeeUpdate,
    current_user: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Обновить информацию о сотруднике (только для админов)"""
    result = await db.execute(select(Employee).where(Employee.id == employee_id))
    employee = result.scalar_one_or_none()
    
    if not employee:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    
    # Обновляем только переданные поля
    update_data = employee_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(employee, field, value)
    
    await db.commit()
    await db.refresh(employee)
    
    return employee


@router.delete("/{employee_id}")
async def delete_employee(
    employee_id: int,
    current_user: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Удалить сотрудника (только для админов)"""
    result = await db.execute(select(Employee).where(Employee.id == employee_id))
    employee = result.scalar_one_or_none()
    
    if not employee:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    
    # Нельзя удалять самого себя
    if employee.id == current_user.get('employee_id'):
        raise HTTPException(
            status_code=400,
            detail="Нельзя удалить самого себя"
        )
    
    await db.delete(employee)
    await db.commit()
    
    return {"message": "Сотрудник успешно удален"}


@router.get("/{employee_id}/statistics")
async def get_employee_statistics(
    employee_id: int,
    period: str = "today",
    current_user: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Получить статистику конкретного сотрудника (только для админов)"""
    # Проверяем, что сотрудник существует
    result = await db.execute(select(Employee).where(Employee.id == employee_id))
    employee = result.scalar_one_or_none()
    
    if not employee:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    
    # Определяем период
    if period == "today":
        start_date = datetime.combine(datetime.utcnow().date(), datetime.min.time())
    elif period == "week":
        today = datetime.utcnow().date()
        start_date = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())
    else:  # month
        today = datetime.utcnow().date()
        start_date = datetime.combine(today.replace(day=1), datetime.min.time())
    
    # Получаем сообщения сотрудника
    messages_result = await db.execute(
        select(Message).where(
            and_(
                Message.employee_id == employee_id,
                Message.received_at >= start_date
            )
        )
    )
    messages = messages_result.scalars().all()
    
    total = len(messages)
    responded = sum(1 for m in messages if m.responded_at is not None)
    missed = total - responded
    
    response_times = [m.response_time_minutes for m in messages if m.response_time_minutes is not None]
    avg_time = sum(response_times) / len(response_times) if response_times else 0
    
    return {
        "employee": {
            "id": employee.id,
            "full_name": employee.full_name,
            "telegram_username": employee.telegram_username
        },
        "period": period,
        "total_messages": total,
        "responded_messages": responded,
        "missed_messages": missed,
        "avg_response_time": round(avg_time, 1),
        "response_rate": round((responded / total * 100) if total > 0 else 0, 1)
    } 