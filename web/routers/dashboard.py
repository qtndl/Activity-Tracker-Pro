from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime, timedelta
from pydantic import BaseModel

from database.database import get_db
from database.models import Employee, Message, SystemSettings
from web.auth import get_current_user, get_current_admin
from web.services.google_sheets import GoogleSheetsService
from config.config import settings

router = APIRouter()


class DashboardSettings(BaseModel):
    google_sheets_enabled: bool
    
    
@router.get("/overview")
async def get_dashboard_overview(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Получить обзор для дашборда"""
    today = datetime.utcnow().date()
    start_of_day = datetime.combine(today, datetime.min.time())
    
    if current_user.get('is_admin'):
        # Для админа - общая статистика
        # Активные сотрудники
        active_employees = await db.execute(
            select(Employee).where(Employee.is_active == True)
        )
        active_count = len(active_employees.scalars().all())
        
        # Сообщения за сегодня
        today_messages = await db.execute(
            select(Message).where(Message.received_at >= start_of_day)
        )
        messages = today_messages.scalars().all()
        
        total_messages = len(messages)
        responded = sum(1 for m in messages if m.responded_at is not None)
        missed = total_messages - responded
        
        # Средние показатели
        response_times = [m.response_time_minutes for m in messages if m.response_time_minutes is not None]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        
        # Неотвеченные сообщения старше 15 минут
        urgent_messages = await db.execute(
            select(Message).where(
                and_(
                    Message.responded_at.is_(None),
                    Message.received_at < datetime.utcnow() - timedelta(minutes=15)
                )
            )
        )
        urgent_count = len(urgent_messages.scalars().all())
        
        return {
            "active_employees": active_count,
            "total_messages_today": total_messages,
            "responded_today": responded,
            "missed_today": missed,
            "avg_response_time": round(avg_response_time, 1),
            "urgent_messages": urgent_count,
            "efficiency_today": round((responded / total_messages * 100) if total_messages > 0 else 0, 1)
        }
    else:
        # Для сотрудника - личная статистика
        my_messages = await db.execute(
            select(Message).where(
                and_(
                    Message.employee_id == current_user.get('employee_id'),
                    Message.received_at >= start_of_day
                )
            )
        )
        messages = my_messages.scalars().all()
        
        total_messages = len(messages)
        responded = sum(1 for m in messages if m.responded_at is not None)
        missed = total_messages - responded
        
        response_times = [m.response_time_minutes for m in messages if m.response_time_minutes is not None]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        
        # Неотвеченные сообщения
        unanswered = await db.execute(
            select(Message).where(
                and_(
                    Message.employee_id == current_user.get('employee_id'),
                    Message.responded_at.is_(None)
                )
            )
        )
        unanswered_count = len(unanswered.scalars().all())
        
        return {
            "total_messages_today": total_messages,
            "responded_today": responded,
            "missed_today": missed,
            "avg_response_time": round(avg_response_time, 1),
            "unanswered_messages": unanswered_count,
            "efficiency_today": round((responded / total_messages * 100) if total_messages > 0 else 0, 1)
        }


@router.get("/settings")
async def get_dashboard_settings(
    current_user: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
) -> DashboardSettings:
    """Получить настройки дашборда (только для админов)"""
    # Получаем настройку Google Sheets из БД
    result = await db.execute(
        select(SystemSettings).where(SystemSettings.key == "google_sheets_enabled")
    )
    setting = result.scalar_one_or_none()
    
    google_sheets_enabled = setting.value == "true" if setting else settings.google_sheets_enabled
    
    return DashboardSettings(google_sheets_enabled=google_sheets_enabled)


@router.put("/settings")
async def update_dashboard_settings(
    settings_data: DashboardSettings,
    current_user: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Обновить настройки дашборда (только для админов)"""
    # Обновляем настройку Google Sheets
    result = await db.execute(
        select(SystemSettings).where(SystemSettings.key == "google_sheets_enabled")
    )
    setting = result.scalar_one_or_none()
    
    if setting:
        setting.value = "true" if settings_data.google_sheets_enabled else "false"
        setting.updated_at = datetime.utcnow()
    else:
        setting = SystemSettings(
            key="google_sheets_enabled",
            value="true" if settings_data.google_sheets_enabled else "false"
        )
        db.add(setting)
    
    await db.commit()
    
    return {"message": "Настройки успешно обновлены"}


@router.post("/export/google-sheets")
async def export_to_google_sheets(
    period: str = Query("today", regex="^(today|week|month)$"),
    current_user: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Экспортировать статистику в Google Sheets (только для админов)"""
    # Проверяем, включена ли интеграция
    result = await db.execute(
        select(SystemSettings).where(SystemSettings.key == "google_sheets_enabled")
    )
    setting = result.scalar_one_or_none()
    
    if not setting or setting.value != "true":
        raise HTTPException(
            status_code=400,
            detail="Интеграция с Google Sheets отключена"
        )
    
    # Инициализируем сервис Google Sheets
    try:
        sheets_service = GoogleSheetsService()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка инициализации Google Sheets: {str(e)}"
        )
    
    # Определяем период
    if period == "today":
        start_date = datetime.combine(datetime.utcnow().date(), datetime.min.time())
        sheet_name = f"Статистика_{datetime.utcnow().strftime('%Y-%m-%d')}"
    elif period == "week":
        today = datetime.utcnow().date()
        start_date = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())
        sheet_name = f"Статистика_неделя_{start_date.strftime('%Y-%m-%d')}"
    else:  # month
        today = datetime.utcnow().date()
        start_date = datetime.combine(today.replace(day=1), datetime.min.time())
        sheet_name = f"Статистика_месяц_{start_date.strftime('%Y-%m')}"
    
    # Получаем данные
    employees_result = await db.execute(
        select(Employee).where(Employee.is_active == True)
    )
    employees = employees_result.scalars().all()
    
    data = [["Сотрудник", "Всего сообщений", "Отвечено", "Пропущено", 
             "Среднее время ответа (мин)", "Эффективность (%)"]]
    
    for employee in employees:
        messages_result = await db.execute(
            select(Message).where(
                and_(
                    Message.employee_id == employee.id,
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
        efficiency = (responded / total * 100) if total > 0 else 0
        
        data.append([
            employee.full_name,
            total,
            responded,
            missed,
            round(avg_time, 1),
            round(efficiency, 1)
        ])
    
    # Экспортируем в Google Sheets
    try:
        sheet_url = await sheets_service.export_statistics(data, sheet_name)
        return {
            "message": "Данные успешно экспортированы",
            "sheet_url": sheet_url
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка экспорта: {str(e)}"
        ) 