from typing import List, Optional
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
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
        orm_mode = True


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
        orm_mode = True


@router.get("/my", response_model=List[StatisticsResponse])
async def get_my_statistics(
    period_type: str = Query("daily", regex="^(daily|weekly|monthly)$"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Получить свою статистику"""
    query = select(EmployeeStatistics).where(
        EmployeeStatistics.employee_id == current_user.id,
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
            "employee_name": current_user.full_name,
            "efficiency_percent": efficiency
        })
    
    return response


@router.get("/all", response_model=List[StatisticsResponse])
async def get_all_statistics(
    period_type: str = Query("daily", regex="^(daily|weekly|monthly)$"),
    employee_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user: Employee = Depends(get_current_admin),
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
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Получить список сообщений"""
    # Обычный сотрудник может видеть только свои сообщения
    if not current_user.is_admin:
        employee_id = current_user.id
    
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
    current_user: Employee = Depends(get_current_user),
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
    
    # Базовый запрос
    if current_user.is_admin:
        # Админ видит общую статистику
        query = select(
            func.count(Message.id).label('total'),
            func.count(Message.responded_at).label('responded'),
            func.avg(Message.response_time_minutes).label('avg_response_time')
        ).where(
            Message.received_at >= start_date,
            Message.received_at <= end_date
        )
    else:
        # Сотрудник видит только свою
        query = select(
            func.count(Message.id).label('total'),
            func.count(Message.responded_at).label('responded'),
            func.avg(Message.response_time_minutes).label('avg_response_time')
        ).where(
            Message.employee_id == current_user.id,
            Message.received_at >= start_date,
            Message.received_at <= end_date
        )
    
    result = await db.execute(query)
    stats = result.one()
    
    missed = stats.total - stats.responded if stats.total else 0
    efficiency = (stats.responded / stats.total * 100) if stats.total > 0 else 0
    
    # Подсчет превышений времени
    time_query = select(Message.response_time_minutes).where(
        Message.response_time_minutes.isnot(None),
        Message.received_at >= start_date,
        Message.received_at <= end_date
    )
    
    if not current_user.is_admin:
        time_query = time_query.where(Message.employee_id == current_user.id)
    
    time_result = await db.execute(time_query)
    response_times = [r for r, in time_result.all()]
    
    exceeded_15 = sum(1 for t in response_times if t > 15)
    exceeded_30 = sum(1 for t in response_times if t > 30)
    exceeded_60 = sum(1 for t in response_times if t > 60)
    
    return {
        "period": period,
        "total_messages": stats.total or 0,
        "responded_messages": stats.responded or 0,
        "missed_messages": missed,
        "avg_response_time": round(stats.avg_response_time or 0, 1),
        "efficiency_percent": round(efficiency, 1),
        "exceeded_15_min": exceeded_15,
        "exceeded_30_min": exceeded_30,
        "exceeded_60_min": exceeded_60
    }


@router.get("/charts/response-time")
async def get_response_time_chart(
    period: str = Query("week", regex="^(week|month)$"),
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Получить данные для графика времени ответа"""
    # Определяем период
    if period == "week":
        days = 7
    else:  # month
        days = 30
    
    start_date = datetime.utcnow() - timedelta(days=days)
    
    # Получаем данные по дням
    query = select(
        func.date(Message.received_at).label('date'),
        func.avg(Message.response_time_minutes).label('avg_time'),
        func.count(Message.id).label('count')
    ).where(
        Message.received_at >= start_date,
        Message.response_time_minutes.isnot(None)
    )
    
    if not current_user.is_admin:
        query = query.where(Message.employee_id == current_user.id)
    
    query = query.group_by(func.date(Message.received_at)).order_by('date')
    
    result = await db.execute(query)
    data = result.all()
    
    return {
        "labels": [str(d.date) for d in data],
        "data": [round(d.avg_time, 1) for d in data],
        "counts": [d.count for d in data]
    } 