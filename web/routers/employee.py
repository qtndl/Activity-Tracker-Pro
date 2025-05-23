"""Роутеры для личного кабинета сотрудника"""

from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc

from database.database import get_db
from database.models import Employee, Message, EmployeeStatistics
from web.auth import get_current_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Шаблоны
templates = Jinja2Templates(directory="web/templates")


@router.get("/dashboard", response_class=HTMLResponse)
async def employee_dashboard(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Личный дашборд сотрудника"""
    
    employee_id = current_user.get("employee_id")
    
    # Получаем статистику сотрудника за сегодня
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    
    # Статистика сообщений
    messages_result = await db.execute(
        select(Message).where(
            and_(
                Message.employee_id == employee_id,
                Message.received_at >= today_start,
                Message.received_at <= today_end,
                Message.message_type == "client"
            )
        )
    )
    messages = messages_result.scalars().all()
    
    # Вычисляем статистику
    total_messages = len(messages)
    responded_messages = len([m for m in messages if m.responded_at])
    missed_messages = total_messages - responded_messages
    
    # Среднее время ответа
    response_times = [m.response_time_minutes for m in messages if m.response_time_minutes]
    avg_response_time = sum(response_times) / len(response_times) if response_times else 0
    
    # Превышения времени
    exceeded_15_min = len([m for m in messages if m.response_time_minutes and m.response_time_minutes > 15])
    exceeded_30_min = len([m for m in messages if m.response_time_minutes and m.response_time_minutes > 30])
    exceeded_60_min = len([m for m in messages if m.response_time_minutes and m.response_time_minutes > 60])
    
    # Последние 10 сообщений
    recent_messages_result = await db.execute(
        select(Message).where(
            and_(
                Message.employee_id == employee_id,
                Message.message_type == "client"
            )
        ).order_by(desc(Message.received_at)).limit(10)
    )
    recent_messages = recent_messages_result.scalars().all()
    
    # Формируем объект статистики
    stats = type('Stats', (), {
        'total_messages': total_messages,
        'responded_messages': responded_messages,
        'missed_messages': missed_messages,
        'avg_response_time': avg_response_time,
        'exceeded_15_min': exceeded_15_min,
        'exceeded_30_min': exceeded_30_min,
        'exceeded_60_min': exceeded_60_min
    })()
    
    return templates.TemplateResponse("employee_dashboard.html", {
        "request": request,
        "user": current_user,
        "stats": stats,
        "recent_messages": recent_messages
    })


@router.get("/my-stats")
async def get_my_stats(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    period: str = "today"
):
    """API для получения статистики сотрудника"""
    
    employee_id = current_user.get("employee_id")
    
    # Определяем период
    if period == "today":
        start_date = datetime.utcnow().date()
        end_date = start_date
    elif period == "week":
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=7)
    elif period == "month":
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=30)
    else:
        start_date = datetime.utcnow().date()
        end_date = start_date
    
    start_datetime = datetime.combine(start_date, datetime.min.time())
    end_datetime = datetime.combine(end_date, datetime.max.time())
    
    # Получаем сообщения за период
    messages_result = await db.execute(
        select(Message).where(
            and_(
                Message.employee_id == employee_id,
                Message.received_at >= start_datetime,
                Message.received_at <= end_datetime,
                Message.message_type == "client"
            )
        )
    )
    messages = messages_result.scalars().all()
    
    # Вычисляем статистику
    total_messages = len(messages)
    responded_messages = len([m for m in messages if m.responded_at])
    missed_messages = total_messages - responded_messages
    
    response_times = [m.response_time_minutes for m in messages if m.response_time_minutes]
    avg_response_time = sum(response_times) / len(response_times) if response_times else 0
    
    return {
        "period": period,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "total_messages": total_messages,
        "responded_messages": responded_messages,
        "missed_messages": missed_messages,
        "avg_response_time": avg_response_time,
        "response_rate": (responded_messages / total_messages * 100) if total_messages > 0 else 0
    }


@router.get("/my-messages")
async def get_my_messages(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    offset: int = 0
):
    """API для получения сообщений сотрудника"""
    
    employee_id = current_user.get("employee_id")
    
    # Получаем сообщения
    messages_result = await db.execute(
        select(Message).where(
            and_(
                Message.employee_id == employee_id,
                Message.message_type == "client"
            )
        ).order_by(desc(Message.received_at)).limit(limit).offset(offset)
    )
    messages = messages_result.scalars().all()
    
    # Форматируем для API
    formatted_messages = []
    for message in messages:
        formatted_messages.append({
            "id": message.id,
            "client_name": message.client_name,
            "client_username": message.client_username,
            "message_text": message.message_text,
            "received_at": message.received_at.isoformat(),
            "responded_at": message.responded_at.isoformat() if message.responded_at else None,
            "response_time_minutes": message.response_time_minutes,
            "is_responded": bool(message.responded_at)
        })
    
    return {
        "messages": formatted_messages,
        "limit": limit,
        "offset": offset,
        "total": len(formatted_messages)
    } 