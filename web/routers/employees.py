from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_, func, desc
from datetime import datetime, timedelta
from pydantic import BaseModel

from database.database import get_db
from database.models import Employee, Message
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
    """Получить статистику конкретного сотрудника (только для админов) - ЕДИНЫЙ ИСТОЧНИК ДАННЫХ"""
    
    # Импортируем сервис
    from web.services.statistics_service import StatisticsService
    
    stats_service = StatisticsService(db)
    
    try:
        stats = await stats_service.get_employee_stats(employee_id, period=period)
        
        return {
            "employee": {
                "id": stats.employee_id,
                "full_name": stats.employee_name,
                "telegram_username": stats.telegram_username
            },
            "period": period,
            "total_messages": stats.total_messages,
            "responded_messages": stats.responded_messages,
            "missed_messages": stats.missed_messages,
            "unique_clients": stats.unique_clients,
            "avg_response_time": round(stats.avg_response_time or 0, 1),
            "response_rate": round(stats.response_rate, 1)
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")


@router.post("/{employee_id}/toggle-active")
async def toggle_employee_active(
    employee_id: int,
    current_user: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Переключить статус активности сотрудника (только для админов)"""
    print(f"Attempting to toggle active status for employee {employee_id}")
    print(f"Current user: {current_user}")
    
    result = await db.execute(select(Employee).where(Employee.id == employee_id))
    employee = result.scalar_one_or_none()
    
    if not employee:
        print(f"Employee {employee_id} not found")
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    
    print(f"Found employee: {employee.id}, current user: {current_user.get('employee_id')}")
    
    # Нельзя деактивировать самого себя
    if employee.id == current_user.get('employee_id'):
        print(f"Cannot deactivate self: {employee.id}")
        raise HTTPException(
            status_code=400,
            detail="Нельзя деактивировать самого себя"
        )
    
    # Переключаем статус
    employee.is_active = not employee.is_active
    await db.commit()
    await db.refresh(employee)
    
    print(f"Successfully toggled status to {employee.is_active}")
    return {"success": True, "is_active": employee.is_active} 