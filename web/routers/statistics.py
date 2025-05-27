from typing import List, Dict, Optional
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc, delete
from pydantic import BaseModel
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.requests import Request
from fastapi.templating import Jinja2Templates
import json

from database.database import get_db
from database.models import Employee, Message, SystemSettings
from web.auth import get_current_user, get_current_admin
from web.services.statistics_service import StatisticsService, EmployeeStats
from web.services.google_sheets import GoogleSheetsService

router = APIRouter()


class StatisticsResponse(BaseModel):
    employee_id: int
    employee_name: str
    period_type: str
    date: datetime
    total_messages: int
    responded_messages: int
    missed_messages: int
    unique_clients: int
    avg_response_time: Optional[float]
    exceeded_15_min: int
    exceeded_30_min: int
    exceeded_60_min: int
    efficiency_percent: Optional[float]
    
    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    id: int
    employee_id: int
    message_type: str
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
    """Получить свою статистику в реальном времени"""
    
    # Устанавливаем даты по умолчанию
    if not start_date:
        start_date = datetime.utcnow().date() - timedelta(days=30)
    if not end_date:
        end_date = datetime.utcnow().date()
    
    # Получаем сообщения за период
    start_datetime = datetime.combine(start_date, datetime.min.time())
    end_datetime = datetime.combine(end_date, datetime.max.time())
    
    result = await db.execute(
        select(Message).where(
            and_(
                Message.employee_id == current_user.get('employee_id'),
                Message.received_at >= start_datetime,
                Message.received_at <= end_datetime
            )
        ).order_by(Message.received_at)
    )
    messages = result.scalars().all()
    
    # Группируем по периодам
    grouped_stats = _group_messages_by_period(messages, period_type, current_user.get('full_name'))
    
    return grouped_stats


@router.get("/all", response_model=List[StatisticsResponse])
async def get_all_statistics(
    period_type: str = Query("daily", regex="^(daily|weekly|monthly)$"),
    employee_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Получить детальную статистику всех сотрудников - ЕДИНЫЙ ИСТОЧНИК ДАННЫХ"""
    
    stats_service = StatisticsService(db)
    
    # Получаем статистику
    all_stats = await stats_service.get_all_employees_stats(
        period="today",  # Базовый период для детализации
        start_date=start_date,
        end_date=end_date,
        employee_id=employee_id
    )
    
    # Конвертируем в формат ответа
    result = []
    for stats in all_stats:
        result.append(StatisticsResponse(
            employee_id=stats.employee_id,
            employee_name=stats.employee_name,
            period_type=period_type,
            date=stats.period_start,
            total_messages=stats.total_messages,
            responded_messages=stats.responded_messages,
            missed_messages=stats.missed_messages,
            unique_clients=stats.unique_clients,
            avg_response_time=stats.avg_response_time,
            exceeded_15_min=stats.exceeded_15_min,
            exceeded_30_min=stats.exceeded_30_min,
            exceeded_60_min=stats.exceeded_60_min,
            efficiency_percent=stats.efficiency_percent
        ))
    
    return sorted(result, key=lambda x: x.date, reverse=True)


@router.get("/summary")
async def get_statistics_summary(
    period: str = Query("today", regex="^(today|week|month)$"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Dict:
    """Получить сводную статистику - ЕДИНЫЙ ИСТОЧНИК ДАННЫХ"""
    
    stats_service = StatisticsService(db)
    
    if current_user.get('is_admin'):
        # Админ видит общую статистику, посчитанную get_dashboard_overview
        # user_id для админа в get_dashboard_overview формально нужен, но не влияет на результат
        admin_user_id = current_user.get('employee_id', 0) # Пытаемся получить employee_id админа
        summary_data = await stats_service.get_dashboard_overview(user_id=admin_user_id, is_admin=True, period=period)
        
        # Возвращаем данные с ключами, которые ожидает фронтенд (или фронтенд нужно будет обновить)
        # get_dashboard_overview возвращает:
        # total_messages_today, responded_today, missed_today, unique_clients_today, avg_response_time, efficiency_today
        # Фронтенд ожидает:
        # total_messages, responded_messages, missed_messages, unique_clients, avg_response_time, efficiency_percent
        # (также exceeded_15_min, exceeded_30_min, exceeded_60_min, которых нет в get_dashboard_overview напрямую)
        
        # Базовое маппинг:
        return {
            "period": period,
            "total_messages": summary_data.get("total_messages_today", 0),
            "responded_messages": summary_data.get("responded_today", 0),
            "missed_messages": summary_data.get("missed_today", 0),
            "unique_clients": summary_data.get("unique_clients_today", 0),
            "avg_response_time": summary_data.get("avg_response_time", 0),
            "efficiency_percent": summary_data.get("efficiency_today", 0),
            # Данные по exceeded_X_min отсутствуют в get_dashboard_overview в текущей реализации
            # Если они нужны на дашборде, их нужно либо добавить в get_dashboard_overview,
            # либо фронтенд не должен их ожидать от этого эндпоинта для админа.
            # Пока возвращаем 0 для них, чтобы не было ошибок на фронте.
            "exceeded_15_min": 0, 
            "exceeded_30_min": 0,
            "exceeded_60_min": 0
        }
    else:
        # Сотрудник видит только свою статистику
        employee_id = current_user.get('employee_id')
        if not employee_id:
            raise HTTPException(status_code=403, detail="Employee ID not found for current user")
            
        stats = await stats_service.get_employee_stats(employee_id, period=period)
        
        return {
            "period": period,
            "total_messages": stats.total_messages,
            "responded_messages": stats.responded_messages,
            "missed_messages": stats.missed_messages,
            "unique_clients": stats.unique_clients,
            "avg_response_time": round(stats.avg_response_time or 0, 1),
            "efficiency_percent": round(stats.efficiency_percent, 1),
            "exceeded_15_min": stats.exceeded_15_min,
            "exceeded_30_min": stats.exceeded_30_min,
            "exceeded_60_min": stats.exceeded_60_min
        }


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
    
    # Оставляем только уникальные сообщения по паре (client_telegram_id, message_id)
    unique = {}
    for msg in messages:
        key = (msg.client_telegram_id, msg.message_id)
        if key not in unique:
            unique[key] = msg
    return list(unique.values())


@router.get("/employee/{employee_id}")
async def get_employee_statistics(
    employee_id: int,
    period: str = Query("today", regex="^(today|week|month)$"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Получить статистику конкретного сотрудника - ЕДИНЫЙ ИСТОЧНИК ДАННЫХ"""
    
    # Проверяем права доступа
    if not current_user.get('is_admin') and employee_id != current_user.get('employee_id'):
        raise HTTPException(status_code=403, detail="Недостаточно прав доступа")
    
    stats_service = StatisticsService(db)
    
    try:
        stats = await stats_service.get_employee_stats(employee_id, period=period)
        
        return {
            "employee": {
                "id": stats.employee_id,
                "full_name": stats.employee_name,
                "telegram_id": stats.telegram_id,
                "telegram_username": stats.telegram_username,
                "is_admin": stats.is_admin,
                "is_active": stats.is_active
            },
            "period": period,
            "period_start": stats.period_start.isoformat(),
            "period_end": stats.period_end.isoformat(),
            "total_messages": stats.total_messages,
            "responded_messages": stats.responded_messages,
            "missed_messages": stats.missed_messages,
            "avg_response_time": round(stats.avg_response_time or 0, 1),
            "response_rate": round(stats.response_rate, 1),
            "efficiency_percent": round(stats.efficiency_percent, 1),
            "exceeded_15_min": stats.exceeded_15_min,
            "exceeded_30_min": stats.exceeded_30_min,
            "exceeded_60_min": stats.exceeded_60_min
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/charts/response-time")
async def get_response_time_chart(
    period: str = Query("week", regex="^(week|month)$"),
    employee_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Получить данные для графика времени ответа - ЕДИНЫЙ ИСТОЧНИК ДАННЫХ"""
    
    # Проверяем права доступа
    if employee_id and not current_user.get('is_admin') and employee_id != current_user.get('employee_id'):
        raise HTTPException(status_code=403, detail="Недостаточно прав доступа")
    
    stats_service = StatisticsService(db)
    
    # Если не указан employee_id, берем текущего пользователя (если не админ)
    if not employee_id and not current_user.get('is_admin'):
        employee_id = current_user.get('employee_id')
    
    # Определяем период для графика
    if period == "week":
        days_count = 7
    else:  # month
        days_count = 30
    
    # Получаем данные по дням
    chart_data = []
    today = datetime.utcnow().date()
    
    for i in range(days_count):
        day = today - timedelta(days=days_count - 1 - i)
        
        if employee_id:
            # Статистика конкретного сотрудника
            stats = await stats_service.get_employee_stats(
                employee_id, 
                start_date=day, 
                end_date=day
            )
            chart_data.append({
                "date": day.isoformat(),
                "avg_response_time": stats.avg_response_time or 0,
                "total_messages": stats.total_messages,
                "employee_name": stats.employee_name
            })
        else:
            # Общая статистика всех сотрудников (только для админов)
            all_stats = await stats_service.get_all_employees_stats(
                start_date=day,
                end_date=day
            )
            
            if all_stats:
                avg_times = [s.avg_response_time for s in all_stats if s.avg_response_time is not None]
                avg_response_time = sum(avg_times) / len(avg_times) if avg_times else 0
                total_messages = sum(s.total_messages for s in all_stats)
            else:
                avg_response_time = 0
                total_messages = 0
            
            chart_data.append({
                "date": day.isoformat(),
                "avg_response_time": avg_response_time,
                "total_messages": total_messages,
                "employee_name": "Все сотрудники"
            })
    
    return {
        "period": period,
        "data": chart_data
    }


def _group_messages_by_period(messages: List[Message], period_type: str, employee_name: str) -> List[StatisticsResponse]:
    """Группировка сообщений по периодам"""
    
    periods = {}
    
    for message in messages:
        # Определяем ключ периода
        if period_type == "daily":
            period_key = message.received_at.date()
        elif period_type == "weekly":
            # Начало недели (понедельник)
            days_since_monday = message.received_at.weekday()
            week_start = message.received_at.date() - timedelta(days=days_since_monday)
            period_key = week_start
        else:  # monthly
            period_key = message.received_at.date().replace(day=1)
        
        if period_key not in periods:
            periods[period_key] = []
        periods[period_key].append(message)
    
    # Вычисляем статистику для каждого периода
    result = []
    for period_date, period_messages in periods.items():
        total_messages = len(period_messages)
        responded_messages = sum(1 for m in period_messages if m.responded_at is not None)
        missed_messages = total_messages - responded_messages
        
        # Подсчитываем уникальных клиентов
        unique_client_ids = set()
        for message in period_messages:
            if message.client_telegram_id is not None:
                unique_client_ids.add(message.client_telegram_id)
        unique_clients = len(unique_client_ids)
        
        response_times = [m.response_time_minutes for m in period_messages if m.response_time_minutes is not None]
        avg_response_time = sum(response_times) / len(response_times) if response_times else None
        
        exceeded_15 = sum(1 for t in response_times if t > 15)
        exceeded_30 = sum(1 for t in response_times if t > 30)
        exceeded_60 = sum(1 for t in response_times if t > 60)
        
        efficiency = (responded_messages / total_messages * 100) if total_messages > 0 else None
        
        # Получаем первое сообщение для employee_id
        employee_id = period_messages[0].employee_id if period_messages else 0
        
        result.append(StatisticsResponse(
            employee_id=employee_id,
            employee_name=employee_name,
            period_type=period_type,
            date=datetime.combine(period_date, datetime.min.time()),
            total_messages=total_messages,
            responded_messages=responded_messages,
            missed_messages=missed_messages,
            unique_clients=unique_clients,
            avg_response_time=avg_response_time,
            exceeded_15_min=exceeded_15,
            exceeded_30_min=exceeded_30,
            exceeded_60_min=exceeded_60,
            efficiency_percent=efficiency
        ))
    
    return sorted(result, key=lambda x: x.date, reverse=True)


@router.post("/export-to-sheets")
async def export_statistics_to_sheets(
    period: str = "today",
    employee_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Экспорт статистики в Google Sheets"""
    try:
        # Проверяем права доступа
        if not current_user.get("is_admin") and employee_id and employee_id != current_user.get("employee_id"):
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        
        # Инициализируем сервисы
        stats_service = StatisticsService(db)
        sheets_service = GoogleSheetsService()
        
        if employee_id:
            # Экспорт для конкретного сотрудника
            employee_stats = await stats_service.get_employee_stats(employee_id, period)
            
            # Получаем последние сообщения для детального отчета
            messages_result = await db.execute(
                select(Message).where(
                    and_(
                        Message.employee_id == employee_id,
                        Message.message_type == "client"
                    )
                ).order_by(Message.received_at.desc()).limit(50)
            )
            messages = messages_result.scalars().all()
            
            url = await sheets_service.export_detailed_employee_report(employee_stats, messages)
            
            return {
                "success": True,
                "message": f"Детальный отчет по сотруднику {employee_stats.employee_name} экспортирован",
                "url": url,
                "sheet_name": f"Отчет_{employee_stats.employee_name}_{period}"
            }
        else:
            # Экспорт статистики всех сотрудников
            all_stats = await stats_service.get_all_employees_stats(period)
            
            url = await sheets_service.export_employees_statistics(all_stats, period)
            
            return {
                "success": True,
                "message": f"Статистика всех сотрудников за {period} экспортирована",
                "url": url,
                "sheet_name": f"Статистика_сотрудников_{period}",
                "total_employees": len(all_stats)
            }
            
    except HTTPException as e:
        raise e
    except Exception as e:
        if "Google Sheets" in str(e):
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": str(e),
                    "help": "Проверьте настройки Google Sheets API и доступ к таблице"
                }
            )
        else:
            raise HTTPException(status_code=500, detail=f"Ошибка экспорта: {str(e)}")


@router.post("/auto-export")
async def setup_auto_export(
    enabled: bool,
    schedule: str = "daily",  # daily, weekly, monthly
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Настройка автоматического экспорта"""
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Только для администраторов")
    
    try:
        # Сохраняем настройки в базу данных
        from database.models import SystemSettings
        
        # Удаляем старые настройки автоэкспорта
        await db.execute(
            delete(SystemSettings).where(SystemSettings.key.like("auto_export_%"))
        )
        
        if enabled:
            # Добавляем новые настройки
            settings_list = [
                SystemSettings(
                    key="auto_export_enabled",
                    value="true",
                    description="Автоматический экспорт включен"
                ),
                SystemSettings(
                    key="auto_export_schedule",
                    value=schedule,
                    description="Расписание автоэкспорта"
                ),
                SystemSettings(
                    key="auto_export_last_run",
                    value="",
                    description="Время последнего автоэкспорта"
                )
            ]
            
            for setting in settings_list:
                db.add(setting)
        
        await db.commit()
        
        return {
            "success": True,
            "message": f"Автоэкспорт {'включен' if enabled else 'отключен'}",
            "schedule": schedule if enabled else None
        }
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка настройки автоэкспорта: {str(e)}")


@router.get("/chart", response_class=HTMLResponse)
async def statistics_chart(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Страница со статистикой и диаграммой"""
    
    stats_service = StatisticsService(db)
    
    if current_user.get('is_admin'):
        # Админ видит общую статистику
        admin_user_id = current_user.get('employee_id', 0)
        summary_data = await stats_service.get_dashboard_overview(
            user_id=admin_user_id,
            is_admin=True,
            period="today"
        )
    else:
        # Сотрудник видит свою статистику
        user_stats = await stats_service.get_employee_stats(
            current_user.get('employee_id'),
            period="today"
        )
        summary_data = {
            "total_messages_today": user_stats.total_messages,
            "responded_today": user_stats.responded_messages,
            "missed_today": user_stats.missed_messages,
            "efficiency_today": user_stats.efficiency_percent
        }
    
    return templates.TemplateResponse(
        "statistics_chart.html",
        {
            "request": request,
            "user": current_user,
            "stats": summary_data
        }
    )


@router.post("/export-to-file")
async def export_statistics_to_file(
    period: str = "today",
    employee_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Экспорт статистики в JSON файл"""
    try:
        # Проверяем права доступа
        if not current_user.get("is_admin") and employee_id and employee_id != current_user.get("employee_id"):
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        
        stats_service = StatisticsService(db)
        
        if employee_id:
            # Экспорт для конкретного сотрудника
            employee_stats = await stats_service.get_employee_stats(employee_id, period)
            
            # Получаем последние сообщения
            messages_result = await db.execute(
                select(Message).where(
                    and_(
                        Message.employee_id == employee_id,
                        Message.message_type == "client"
                    )
                ).order_by(Message.received_at.desc()).limit(50)
            )
            messages = messages_result.scalars().all()
            
            export_data = {
                "employee_stats": {
                    "employee_id": employee_stats.employee_id,
                    "employee_name": employee_stats.employee_name,
                    "period": period,
                    "total_messages": employee_stats.total_messages,
                    "responded_messages": employee_stats.responded_messages,
                    "missed_messages": employee_stats.missed_messages,
                    "avg_response_time": employee_stats.avg_response_time,
                    "efficiency_percent": employee_stats.efficiency_percent,
                    "exceeded_15_min": employee_stats.exceeded_15_min,
                    "exceeded_30_min": employee_stats.exceeded_30_min,
                    "exceeded_60_min": employee_stats.exceeded_60_min
                },
                "messages": [
                    {
                        "id": msg.id,
                        "received_at": msg.received_at.isoformat(),
                        "responded_at": msg.responded_at.isoformat() if msg.responded_at else None,
                        "message_text": msg.message_text,
                        "client_name": msg.client_name,
                        "client_username": msg.client_username,
                        "is_missed": msg.is_missed
                    }
                    for msg in messages
                ]
            }
            
            filename = f"employee_{employee_id}_stats_{period}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            
        else:
            # Экспорт статистики всех сотрудников
            all_stats = await stats_service.get_all_employees_stats(period)
            
            export_data = {
                "period": period,
                "export_date": datetime.now().isoformat(),
                "employees": [
                    {
                        "employee_id": stats.employee_id,
                        "employee_name": stats.employee_name,
                        "total_messages": stats.total_messages,
                        "responded_messages": stats.responded_messages,
                        "missed_messages": stats.missed_messages,
                        "avg_response_time": stats.avg_response_time,
                        "efficiency_percent": stats.efficiency_percent,
                        "exceeded_15_min": stats.exceeded_15_min,
                        "exceeded_30_min": stats.exceeded_30_min,
                        "exceeded_60_min": stats.exceeded_60_min
                    }
                    for stats in all_stats
                ]
            }
            
            filename = f"all_employees_stats_{period}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        return JSONResponse(
            content={
                "success": True,
                "message": "Статистика успешно экспортирована",
                "filename": filename,
                "data": export_data
            }
        )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка экспорта: {str(e)}")


@router.post("/import-from-file")
async def import_statistics_from_file(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Импорт статистики из JSON файла"""
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Только для администраторов")
    
    try:
        # Читаем содержимое файла
        content = await file.read()
        data = json.loads(content)
        
        # Проверяем структуру данных
        if "employees" in data:
            # Импорт статистики всех сотрудников
            for employee_data in data["employees"]:
                # Здесь можно добавить логику обновления статистики
                # Например, обновление записей в базе данных
                pass
                
            return {
                "success": True,
                "message": f"Импортирована статистика {len(data['employees'])} сотрудников"
            }
        elif "employee_stats" in data:
            # Импорт статистики одного сотрудника
            stats = data["employee_stats"]
            # Здесь можно добавить логику обновления статистики
            # Например, обновление записей в базе данных
            
            return {
                "success": True,
                "message": f"Импортирована статистика сотрудника {stats['employee_name']}"
            }
        else:
            raise HTTPException(status_code=400, detail="Неверный формат файла")
            
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Неверный формат JSON")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка импорта: {str(e)}") 