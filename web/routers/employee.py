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
from web.services.statistics_service import StatisticsService
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
    """Личный дашборд сотрудника - ЕДИНЫЙ ИСТОЧНИК ДАННЫХ"""
    
    employee_id = current_user.get("employee_id")
    
    # Используем единый сервис статистики
    stats_service = StatisticsService(db)
    stats = await stats_service.get_employee_stats(employee_id, period="today")
    
    # Получаем последние 10 сообщений
    recent_messages_result = await db.execute(
        select(Message).where(
            and_(
                Message.employee_id == employee_id,
                Message.message_type == "client"
            )
        ).order_by(desc(Message.received_at)).limit(10)
    )
    recent_messages = recent_messages_result.scalars().all()
    
    # Создаем объект статистики для шаблона
    stats_obj = type('Stats', (), {
        'total_messages': stats.total_messages,
        'responded_messages': stats.responded_messages,
        'missed_messages': stats.missed_messages,
        'avg_response_time': stats.avg_response_time or 0,
        'exceeded_15_min': stats.exceeded_15_min,
        'exceeded_30_min': stats.exceeded_30_min,
        'exceeded_60_min': stats.exceeded_60_min
    })()
    
    return templates.TemplateResponse("employee_dashboard.html", {
        "request": request,
        "user": current_user,
        "stats": stats_obj,
        "recent_messages": recent_messages
    })


@router.get("/my-stats")
async def get_my_stats(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    period: str = "today"
):
    """API для получения статистики сотрудника - ЕДИНЫЙ ИСТОЧНИК ДАННЫХ"""
    
    employee_id = current_user.get("employee_id")
    
    # Используем единый сервис статистики
    stats_service = StatisticsService(db)
    stats = await stats_service.get_employee_stats(employee_id, period=period)
    
    return {
        "period": period,
        "start_date": stats.period_start.date().isoformat(),
        "end_date": stats.period_end.date().isoformat(),
        "total_messages": stats.total_messages,
        "responded_messages": stats.responded_messages,
        "missed_messages": stats.missed_messages,
        "avg_response_time": stats.avg_response_time or 0,
        "response_rate": stats.response_rate
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


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Страница профиля"""
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Доступ запрещен")
    return templates.TemplateResponse("profile.html", {
        "request": request,
        "userInfo": current_user
    }) 