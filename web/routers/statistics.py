from typing import List, Dict, Optional
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc
from pydantic import BaseModel

from database.database import get_db
from database.models import Employee, EmployeeStatistics, Message
from web.auth import get_current_user, get_current_admin

router = APIRouter()


class StatisticsResponse(BaseModel):
    employee_id: int
    employee_name: str
    period_type: str
    date: datetime
    total_messages: int
    responded_messages: int
    missed_messages: int
    avg_response_time: Optional[float]
    exceeded_15_min: int
    exceeded_30_min: int
    exceeded_60_min: int
    efficiency_percent: Optional[float]
    
    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    id: int
    chat_id: int
    client_username: Optional[str]
    client_name: Optional[str]
    message_text: Optional[str]
    received_at: datetime
    responded_at: Optional[datetime]
    response_time_minutes: Optional[float]
    is_missed: bool
    
    class Config:
        from_attributes = True


@router.get("/my", response_model=List[StatisticsResponse])
async def get_my_statistics(
    period_type: str = Query("daily", regex="^(daily|weekly|monthly)$"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Получить свою статистику"""
    query = select(EmployeeStatistics).where(
        EmployeeStatistics.employee_id == current_user.get('employee_id'),
        EmployeeStatistics.period_type == period_type
    )
    
    if start_date:
        query = query.where(EmployeeStatistics.date >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.where(EmployeeStatistics.date <= datetime.combine(end_date, datetime.max.time()))
    
    result = await db.execute(query.order_by(EmployeeStatistics.date.desc()))
    stats = result.scalars().all()
    
    # Добавляем имя сотрудника и процент эффективности
    response = []
    for stat in stats:
        efficiency = (stat.responded_messages / stat.total_messages * 100) if stat.total_messages > 0 else None
        response.append({
            **stat.__dict__,
            "employee_name": current_user.get('full_name'),
            "efficiency_percent": efficiency
        })
    
    return response


@router.get("/all", response_model=List[StatisticsResponse])
async def get_all_statistics(
    period_type: str = Query("daily", regex="^(daily|weekly|monthly)$"),
    employee_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Получить статистику всех сотрудников (только для админов)"""
    query = select(EmployeeStatistics, Employee).join(
        Employee, EmployeeStatistics.employee_id == Employee.id
    ).where(EmployeeStatistics.period_type == period_type)
    
    if employee_id:
        query = query.where(EmployeeStatistics.employee_id == employee_id)
    if start_date:
        query = query.where(EmployeeStatistics.date >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.where(EmployeeStatistics.date <= datetime.combine(end_date, datetime.max.time()))
    
    result = await db.execute(query.order_by(EmployeeStatistics.date.desc()))
    stats_with_employees = result.all()
    
    response = []
    for stat, employee in stats_with_employees:
        efficiency = (stat.responded_messages / stat.total_messages * 100) if stat.total_messages > 0 else None
        response.append({
            **stat.__dict__,
            "employee_name": employee.full_name,
            "efficiency_percent": efficiency
        })
    
    return response


@router.get("/messages", response_model=List[MessageResponse])
async def get_messages(
    employee_id: Optional[int] = None,
    is_missed: Optional[bool] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = Query(100, le=1000),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Получить список сообщений"""
    # Обычный сотрудник может видеть только свои сообщения
    if not current_user.get('is_admin'):
        employee_id = current_user.get('employee_id')
    
    query = select(Message)
    
    if employee_id:
        query = query.where(Message.employee_id == employee_id)
    if is_missed is not None:
        query = query.where(Message.is_missed == is_missed)
    if start_date:
        query = query.where(Message.received_at >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.where(Message.received_at <= datetime.combine(end_date, datetime.max.time()))
    
    query = query.order_by(Message.received_at.desc()).limit(limit)
    
    result = await db.execute(query)
    messages = result.scalars().all()
    
    return messages


@router.get("/summary")
async def get_summary(
    period: str = Query("today", regex="^(today|week|month)$"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Получить сводку по статистике"""
    # Определяем период
    if period == "today":
        start_date = datetime.combine(datetime.utcnow().date(), datetime.min.time())
    elif period == "week":
        today = datetime.utcnow().date()
        start_date = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())
    else:  # month
        today = datetime.utcnow().date()
        start_date = datetime.combine(today.replace(day=1), datetime.min.time())
    
    end_date = datetime.utcnow()
    
    # Фильтр по сотруднику
    query_filter = Message.received_at >= start_date
    if not current_user.get('is_admin'):
        query_filter = and_(query_filter, Message.employee_id == current_user.get('employee_id'))
    
    # Получаем сообщения
    result = await db.execute(select(Message).where(query_filter))
    messages = result.scalars().all()
    
    total_messages = len(messages)
    responded_messages = sum(1 for m in messages if m.responded_at is not None)
    missed_messages = total_messages - responded_messages
    
    # Время ответа
    response_times = [m.response_time_minutes for m in messages if m.response_time_minutes is not None]
    avg_response_time = sum(response_times) / len(response_times) if response_times else 0
    
    # Подсчет превышений времени
    exceeded_15 = sum(1 for t in response_times if t > 15)
    exceeded_30 = sum(1 for t in response_times if t > 30)
    exceeded_60 = sum(1 for t in response_times if t > 60)
    
    return {
        "period": period,
        "total_messages": total_messages,
        "responded_messages": responded_messages,
        "missed_messages": missed_messages,
        "avg_response_time": round(avg_response_time, 1),
        "efficiency_percent": round((responded_messages / total_messages * 100) if total_messages > 0 else 0, 1),
        "exceeded_15_min": exceeded_15,
        "exceeded_30_min": exceeded_30,
        "exceeded_60_min": exceeded_60
    }


@router.get("/charts/response-time")
async def get_response_time_chart(
    period: str = Query("week", regex="^(week|month)$"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Получить данные для графика времени ответа"""
    # Определяем период
    if period == "week":
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=7)
        date_format = "%Y-%m-%d"
        group_by_days = True
    else:  # month
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=30)
        date_format = "%Y-%m-%d"
        group_by_days = True
    
    start_datetime = datetime.combine(start_date, datetime.min.time())
    
    # Фильтр по сотруднику
    query_filter = and_(
        Message.received_at >= start_datetime,
        Message.response_time_minutes.is_not(None)
    )
    if not current_user.get('is_admin'):
        query_filter = and_(query_filter, Message.employee_id == current_user.get('employee_id'))
    
    # Получаем сообщения с временем ответа
    result = await db.execute(select(Message).where(query_filter))
    messages = result.scalars().all()
    
    # Группируем по дням
    daily_stats = {}
    current_date = start_date
    while current_date <= end_date:
        daily_stats[current_date.strftime(date_format)] = []
        current_date += timedelta(days=1)
    
    for message in messages:
        date_key = message.received_at.strftime(date_format)
        if date_key in daily_stats:
            daily_stats[date_key].append(message.response_time_minutes)
    
    # Вычисляем средние значения
    labels = []
    data = []
    for date_key in sorted(daily_stats.keys()):
        response_times = daily_stats[date_key]
        avg_time = sum(response_times) / len(response_times) if response_times else 0
        
        labels.append(date_key)
        data.append(round(avg_time, 1))
    
    return {
        "labels": labels,
        "data": data,
        "period": period
    } 