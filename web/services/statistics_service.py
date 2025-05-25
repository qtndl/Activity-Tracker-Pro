#!/usr/bin/env python3
"""Единый сервис для вычисления статистики"""

from typing import List, Dict, Optional, Any
from datetime import datetime, date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from dataclasses import dataclass

from database.models import Employee, Message


@dataclass
class EmployeeStats:
    """Статистика сотрудника"""
    employee_id: int
    employee_name: str
    telegram_id: int
    telegram_username: Optional[str]
    is_admin: bool
    is_active: bool
    
    # Основная статистика
    total_messages: int
    responded_messages: int
    missed_messages: int
    deleted_messages: int  # Количество удаленных сообщений
    unique_clients: int  # Количество уникальных клиентов
    avg_response_time: Optional[float]
    
    # Превышения времени
    exceeded_15_min: int
    exceeded_30_min: int
    exceeded_60_min: int
    
    # Эффективность
    response_rate: float
    efficiency_percent: float
    
    # Период
    period_start: datetime
    period_end: datetime
    period_name: str


class StatisticsService:
    """Единый сервис для работы со статистикой"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_employee_stats(
        self, 
        employee_id: int, 
        period: str = "today",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> EmployeeStats:
        """Получить статистику конкретного сотрудника"""
        
        # Проверяем что employee_id передан
        if employee_id is None:
            raise ValueError("employee_id не может быть None")
        
        # Получаем информацию о сотруднике
        employee_result = await self.db.execute(
            select(Employee).where(Employee.id == employee_id)
        )
        employee = employee_result.scalar_one_or_none()
        if not employee:
            raise ValueError(f"Сотрудник с ID {employee_id} не найден в базе данных")
        
        # Определяем период
        period_start, period_end = self._get_period_dates(period, start_date, end_date)
        
        # Получаем сообщения за период
        messages = await self._get_messages_for_period(employee_id, period_start, period_end)
        
        # Вычисляем статистику
        stats = self._calculate_stats(messages)
        
        return EmployeeStats(
            employee_id=employee.id,
            employee_name=employee.full_name,
            telegram_id=employee.telegram_id,
            telegram_username=employee.telegram_username,
            is_admin=employee.is_admin,
            is_active=employee.is_active,
            period_start=period_start,
            period_end=period_end,
            period_name=period,
            **stats
        )
    
    async def get_all_employees_stats(
        self,
        period: str = "today",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        employee_id: Optional[int] = None
    ) -> List[EmployeeStats]:
        """Получить статистику всех сотрудников"""
        
        # Получаем список сотрудников
        employee_query = select(Employee)
        if employee_id:
            employee_query = employee_query.where(Employee.id == employee_id)
        
        employees_result = await self.db.execute(employee_query)
        employees = employees_result.scalars().all()
        
        # Определяем период
        period_start, period_end = self._get_period_dates(period, start_date, end_date)
        
        # Получаем статистику для каждого сотрудника
        all_stats = []
        for employee in employees:
            messages = await self._get_messages_for_period(employee.id, period_start, period_end)
            stats = self._calculate_stats(messages)
            
            all_stats.append(EmployeeStats(
                employee_id=employee.id,
                employee_name=employee.full_name,
                telegram_id=employee.telegram_id,
                telegram_username=employee.telegram_username,
                is_admin=employee.is_admin,
                is_active=employee.is_active,
                period_start=period_start,
                period_end=period_end,
                period_name=period,
                **stats
            ))
        
        return all_stats
    
    async def get_dashboard_overview(self, user_id: int, is_admin: bool, period: str = "today") -> Dict[str, Any]:
        """Получить данные для дашборда"""
        
        if is_admin:
            # Админ видит общую статистику
            all_stats = await self.get_all_employees_stats(period)
            
            # Считаем общие показатели
            total_messages = sum(s.total_messages for s in all_stats)
            responded = sum(s.responded_messages for s in all_stats)
            missed = sum(s.missed_messages for s in all_stats)
            total_unique_clients = sum(s.unique_clients for s in all_stats)
            
            # Среднее время ответа по всем сотрудникам
            avg_times = [s.avg_response_time for s in all_stats if s.avg_response_time is not None]
            avg_response_time = sum(avg_times) / len(avg_times) if avg_times else 0
            
            # Количество активных сотрудников
            active_employees = len([s for s in all_stats if s.is_active])
            
            # Срочные сообщения (без ответа более 30 минут) - всегда актуальные
            urgent_messages = await self._get_urgent_messages_count()
            
            return {
                "active_employees": active_employees,
                "total_messages_today": total_messages,
                "responded_today": responded,
                "missed_today": missed,
                "unique_clients_today": total_unique_clients,
                "avg_response_time": round(avg_response_time, 1),
                "urgent_messages": urgent_messages,
                "efficiency_today": round((responded / total_messages * 100) if total_messages > 0 else 0, 1)
            }
        else:
            # Сотрудник видит только свою статистику
            user_stats = await self.get_employee_stats(user_id, period)
            
            # Количество неотвеченных сообщений
            unanswered = await self._get_unanswered_messages_count(user_id)
            
            return {
                "total_messages_today": user_stats.total_messages,
                "responded_today": user_stats.responded_messages,
                "missed_today": user_stats.missed_messages,
                "unique_clients_today": user_stats.unique_clients,
                "avg_response_time": round(user_stats.avg_response_time or 0, 1),
                "unanswered_messages": unanswered,
                "efficiency_today": round(user_stats.efficiency_percent, 1)
            }
    
    def _get_period_dates(
        self, 
        period: str, 
        start_date: Optional[date] = None, 
        end_date: Optional[date] = None
    ) -> tuple[datetime, datetime]:
        """Получить даты начала и конца периода"""
        
        if start_date and end_date:
            return (
                datetime.combine(start_date, datetime.min.time()),
                datetime.combine(end_date, datetime.max.time())
            )
        
        now = datetime.utcnow()
        today = now.date()
        
        if period == "today":
            # Используем текущее время как конец периода
            return (
                datetime.combine(today, datetime.min.time()),
                now  # Текущее время
            )
        elif period == "week":
            start = today - timedelta(days=today.weekday())  # Понедельник
            end = start + timedelta(days=6)  # Воскресенье
            return (
                datetime.combine(start, datetime.min.time()),
                datetime.combine(end, datetime.max.time())
            )
        elif period == "month":
            start = today.replace(day=1)  # Первое число месяца
            if today.month == 12:
                end = date(today.year + 1, 1, 1) - timedelta(days=1)
            else:
                end = date(today.year, today.month + 1, 1) - timedelta(days=1)
            return (
                datetime.combine(start, datetime.min.time()),
                datetime.combine(end, datetime.max.time())
            )
        else:
            # По умолчанию - сегодня
            return (
                datetime.combine(today, datetime.min.time()),
                now  # Текущее время
            )
    
    async def _get_messages_for_period(
        self, 
        employee_id: int, 
        start_date: datetime, 
        end_date: datetime
    ) -> List[Message]:
        """Получить сообщения сотрудника за период"""
        
        # Получаем все сообщения сотрудника
        result = await self.db.execute(
            select(Message).where(
                Message.employee_id == employee_id
            ).order_by(Message.received_at)
        )
        messages = result.scalars().all()
        
        # Фильтруем по времени вручную
        filtered_messages = []
        for msg in messages:
            # Приводим время сообщения к UTC
            msg_time = msg.received_at.replace(tzinfo=None)
            if start_date <= msg_time <= end_date:
                filtered_messages.append(msg)
        
        return filtered_messages
    
    def _calculate_stats(self, messages: List[Message]) -> Dict[str, Any]:
        """Вычислить статистику по списку сообщений"""
        
        total_messages = len(messages)
        responded_messages = len([m for m in messages if m.responded_at is not None])
        
        # Удаленные сообщения не считаются пропущенными
        deleted_messages = len([m for m in messages if m.is_deleted])
        # Пропущенные = всего - отвечено - удалено
        missed_messages = total_messages - responded_messages - deleted_messages
        
        # Уникальные клиенты (по Telegram ID) - включая клиентов удаленных сообщений
        unique_client_ids = set()
        for msg in messages:
            if msg.client_telegram_id is not None:
                unique_client_ids.add(msg.client_telegram_id)
        unique_clients = len(unique_client_ids)
        
        # Время ответа (только для отвеченных сообщений)
        response_times = [m.response_time_minutes for m in messages if m.response_time_minutes is not None]
        avg_response_time = sum(response_times) / len(response_times) if response_times else None
        
        # Превышения времени (только для отвеченных сообщений)
        exceeded_15_min = len([t for t in response_times if t > 15])
        exceeded_30_min = len([t for t in response_times if t > 30])
        exceeded_60_min = len([t for t in response_times if t > 60])
        
        # Эффективность (отвеченные + удаленные считаются "обработанными")
        processed_messages = responded_messages + deleted_messages
        response_rate = (processed_messages / total_messages * 100) if total_messages > 0 else 0
        efficiency_percent = response_rate
        
        return {
            "total_messages": total_messages,
            "responded_messages": responded_messages,
            "missed_messages": missed_messages,
            "deleted_messages": deleted_messages,
            "unique_clients": unique_clients,
            "avg_response_time": avg_response_time,
            "exceeded_15_min": exceeded_15_min,
            "exceeded_30_min": exceeded_30_min,
            "exceeded_60_min": exceeded_60_min,
            "response_rate": response_rate,
            "efficiency_percent": efficiency_percent
        }
    
    async def _get_urgent_messages_count(self) -> int:
        """Получить количество срочных сообщений (без ответа более 30 минут, исключая удаленные)"""
        
        threshold_time = datetime.utcnow() - timedelta(minutes=30)
        
        result = await self.db.execute(
            select(Message).where(
                and_(
                    Message.responded_at.is_(None),
                    Message.is_deleted == False,  # Исключаем удаленные сообщения
                    Message.received_at <= threshold_time,
                    Message.message_type == "client"
                )
            )
        )
        return len(result.scalars().all())
    
    async def _get_unanswered_messages_count(self, employee_id: int) -> int:
        """Получить количество неотвеченных сообщений сотрудника (исключая удаленные)"""
        
        result = await self.db.execute(
            select(Message).where(
                and_(
                    Message.employee_id == employee_id,
                    Message.responded_at.is_(None),
                    Message.is_deleted == False,  # Исключаем удаленные сообщения
                    Message.message_type == "client"
                )
            )
        )
        return len(result.scalars().all()) 