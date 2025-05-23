from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from database.database import AsyncSessionLocal
from database.models import Employee, Message, EmployeeStatistics
import logging

logger = logging.getLogger(__name__)


class AnalyticsService:
    async def calculate_daily_stats(self):
        """Расчет ежедневной статистики для всех сотрудников"""
        async with AsyncSessionLocal() as session:
            # Получаем всех активных сотрудников
            result = await session.execute(
                select(Employee).where(Employee.is_active == True)
            )
            employees = result.scalars().all()
            
            today = datetime.utcnow().date()
            start_of_day = datetime.combine(today, datetime.min.time())
            
            for employee in employees:
                await self._calculate_employee_stats(session, employee.id, start_of_day, 'daily')
    
    async def calculate_weekly_stats(self):
        """Расчет еженедельной статистики"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Employee).where(Employee.is_active == True)
            )
            employees = result.scalars().all()
            
            today = datetime.utcnow().date()
            start_of_week = today - timedelta(days=today.weekday())
            start_date = datetime.combine(start_of_week, datetime.min.time())
            
            for employee in employees:
                await self._calculate_employee_stats(session, employee.id, start_date, 'weekly')
    
    async def calculate_monthly_stats(self):
        """Расчет ежемесячной статистики"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Employee).where(Employee.is_active == True)
            )
            employees = result.scalars().all()
            
            today = datetime.utcnow().date()
            start_of_month = today.replace(day=1)
            start_date = datetime.combine(start_of_month, datetime.min.time())
            
            for employee in employees:
                await self._calculate_employee_stats(session, employee.id, start_date, 'monthly')
    
    async def _calculate_employee_stats(self, session: AsyncSession, employee_id: int, 
                                      start_date: datetime, period_type: str):
        """Расчет статистики для конкретного сотрудника"""
        end_date = datetime.utcnow()
        
        # Получаем все сообщения за период
        result = await session.execute(
            select(Message).where(
                and_(
                    Message.employee_id == employee_id,
                    Message.received_at >= start_date,
                    Message.received_at <= end_date
                )
            )
        )
        messages = result.scalars().all()
        
        # Подсчитываем статистику
        total_messages = len(messages)
        responded_messages = sum(1 for m in messages if m.responded_at is not None)
        missed_messages = total_messages - responded_messages
        
        response_times = [m.response_time_minutes for m in messages if m.response_time_minutes is not None]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        
        exceeded_15_min = sum(1 for t in response_times if t > 15)
        exceeded_30_min = sum(1 for t in response_times if t > 30)
        exceeded_60_min = sum(1 for t in response_times if t > 60)
        
        # Проверяем, существует ли уже статистика
        existing_stats = await session.execute(
            select(EmployeeStatistics).where(
                and_(
                    EmployeeStatistics.employee_id == employee_id,
                    EmployeeStatistics.date == start_date,
                    EmployeeStatistics.period_type == period_type
                )
            )
        )
        stats = existing_stats.scalar_one_or_none()
        
        if stats:
            # Обновляем существующую
            stats.total_messages = total_messages
            stats.responded_messages = responded_messages
            stats.missed_messages = missed_messages
            stats.avg_response_time = avg_response_time
            stats.exceeded_15_min = exceeded_15_min
            stats.exceeded_30_min = exceeded_30_min
            stats.exceeded_60_min = exceeded_60_min
        else:
            # Создаем новую
            stats = EmployeeStatistics(
                employee_id=employee_id,
                date=start_date,
                period_type=period_type,
                total_messages=total_messages,
                responded_messages=responded_messages,
                missed_messages=missed_messages,
                avg_response_time=avg_response_time,
                exceeded_15_min=exceeded_15_min,
                exceeded_30_min=exceeded_30_min,
                exceeded_60_min=exceeded_60_min
            )
            session.add(stats)
        
        await session.commit()
    
    async def get_employee_stats(self, employee_id: int, period_type: str) -> Optional[EmployeeStatistics]:
        """Получение статистики сотрудника"""
        async with AsyncSessionLocal() as session:
            if period_type == 'daily':
                date = datetime.combine(datetime.utcnow().date(), datetime.min.time())
            elif period_type == 'weekly':
                today = datetime.utcnow().date()
                date = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())
            else:  # monthly
                today = datetime.utcnow().date()
                date = datetime.combine(today.replace(day=1), datetime.min.time())
            
            result = await session.execute(
                select(EmployeeStatistics).where(
                    and_(
                        EmployeeStatistics.employee_id == employee_id,
                        EmployeeStatistics.date == date,
                        EmployeeStatistics.period_type == period_type
                    )
                )
            )
            return result.scalar_one_or_none()
    
    async def get_unanswered_messages(self, employee_id: int) -> List[Message]:
        """Получение неотвеченных сообщений сотрудника"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Message).where(
                    and_(
                        Message.employee_id == employee_id,
                        Message.responded_at.is_(None)
                    )
                ).order_by(Message.received_at)
            )
            return result.scalars().all()
    
    async def mark_message_as_missed(self, message_id: int):
        """Отметить сообщение как пропущенное"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Message).where(Message.id == message_id)
            )
            message = result.scalar_one_or_none()
            
            if message and not message.responded_at:
                message.is_missed = True
                await session.commit() 