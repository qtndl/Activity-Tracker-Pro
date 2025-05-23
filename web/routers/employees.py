from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel
from datetime import datetime

from database.database import get_db
from database.models import Employee
from web.auth import get_current_user, get_current_admin

router = APIRouter()


class EmployeeCreate(BaseModel):
    telegram_id: int
    telegram_username: Optional[str]
    full_name: str
    is_admin: bool = False


class EmployeeUpdate(BaseModel):
    full_name: Optional[str]
    is_active: Optional[bool]
    is_admin: Optional[bool]


class EmployeeResponse(BaseModel):
    id: int
    telegram_id: int
    telegram_username: Optional[str]
    full_name: str
    is_active: bool
    is_admin: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True


@router.get("/", response_model=List[EmployeeResponse])
async def get_employees(
    skip: int = 0,
    limit: int = 100,
    current_user: Employee = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Получить список всех сотрудников (только для админов)"""
    result = await db.execute(
        select(Employee).offset(skip).limit(limit)
    )
    employees = result.scalars().all()
    return employees


@router.get("/me", response_model=EmployeeResponse)
async def get_current_employee(
    current_user: Employee = Depends(get_current_user)
):
    """Получить информацию о текущем пользователе"""
    return current_user


@router.get("/{employee_id}", response_model=EmployeeResponse)
async def get_employee(
    employee_id: int,
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Получить информацию о сотруднике"""
    # Обычный сотрудник может видеть только свою информацию
    if not current_user.is_admin and current_user.id != employee_id:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    result = await db.execute(
        select(Employee).where(Employee.id == employee_id)
    )
    employee = result.scalar_one_or_none()
    
    if not employee:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    
    return employee


@router.post("/", response_model=EmployeeResponse)
async def create_employee(
    employee_data: EmployeeCreate,
    current_user: Employee = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Создать нового сотрудника (только для админов)"""
    # Проверяем, не существует ли уже сотрудник с таким telegram_id
    existing = await db.execute(
        select(Employee).where(Employee.telegram_id == employee_data.telegram_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Сотрудник с таким Telegram ID уже существует")
    
    employee = Employee(**employee_data.dict())
    db.add(employee)
    await db.commit()
    await db.refresh(employee)
    
    return employee


@router.put("/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    employee_id: int,
    employee_data: EmployeeUpdate,
    current_user: Employee = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Обновить информацию о сотруднике (только для админов)"""
    result = await db.execute(
        select(Employee).where(Employee.id == employee_id)
    )
    employee = result.scalar_one_or_none()
    
    if not employee:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    
    # Обновляем только переданные поля
    update_data = employee_data.dict(exclude_unset=True)
    if update_data:
        update_data['updated_at'] = datetime.utcnow()
        await db.execute(
            update(Employee).where(Employee.id == employee_id).values(**update_data)
        )
        await db.commit()
        await db.refresh(employee)
    
    return employee


@router.delete("/{employee_id}")
async def delete_employee(
    employee_id: int,
    current_user: Employee = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Удалить сотрудника (только для админов)"""
    result = await db.execute(
        select(Employee).where(Employee.id == employee_id)
    )
    employee = result.scalar_one_or_none()
    
    if not employee:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    
    # Не позволяем удалить самого себя
    if employee.id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя удалить самого себя")
    
    await db.delete(employee)
    await db.commit()
    
    return {"message": "Сотрудник успешно удален"}


@router.post("/{employee_id}/toggle-active")
async def toggle_employee_active(
    employee_id: int,
    current_user: Employee = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Переключить статус активности сотрудника"""
    result = await db.execute(
        select(Employee).where(Employee.id == employee_id)
    )
    employee = result.scalar_one_or_none()
    
    if not employee:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    
    employee.is_active = not employee.is_active
    employee.updated_at = datetime.utcnow()
    await db.commit()
    
    return {
        "message": f"Сотрудник {'активирован' if employee.is_active else 'деактивирован'}",
        "is_active": employee.is_active
    } 