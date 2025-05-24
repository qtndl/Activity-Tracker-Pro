from datetime import datetime, timedelta
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.database import AsyncSessionLocal
from database.models import Message as DBMessage

class AnalyticsService:
    """Сервис для аналитики и статистики"""
    
    async def get_employee_stats(self, employee_id: int, period: str = 'daily') -> dict:
        """Получить статистику сотрудника за период"""
        async with AsyncSessionLocal() as session:
            # Определяем временной диапазон
            now = datetime.utcnow()
            if period == 'daily':
                start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            elif period == 'weekly':
                start_time = now - timedelta(days=7)
            else:
                start_time = now - timedelta(days=30)
            
            # Получаем все сообщения сотрудника за период
            result = await session.execute(
                select(DBMessage).where(
                    and_(
                        DBMessage.employee_id == employee_id,
                        DBMessage.received_at >= start_time
                    )
                )
            )
            messages = result.scalars().all()
            
            if not messages:
                return None
            
            # Считаем статистику
            total_messages = len(messages)
            responded_messages = sum(1 for m in messages if m.responded_at is not None)
            missed_messages = total_messages - responded_messages
            
            # Считаем уникальных клиентов
            unique_client_ids = set()
            for message in messages:
                if message.client_telegram_id is not None:
                    unique_client_ids.add(message.client_telegram_id)
            unique_clients = len(unique_client_ids)
            
            # Считаем среднее время ответа
            response_times = [
                m.response_time_minutes 
                for m in messages 
                if m.response_time_minutes is not None
            ]
            avg_response_time = sum(response_times) / len(response_times) if response_times else 0
            
            # Считаем превышения времени
            exceeded_15_min = sum(1 for m in messages if m.response_time_minutes and m.response_time_minutes > 15)
            exceeded_30_min = sum(1 for m in messages if m.response_time_minutes and m.response_time_minutes > 30)
            exceeded_60_min = sum(1 for m in messages if m.response_time_minutes and m.response_time_minutes > 60)
            
            return {
                'total_messages': total_messages,
                'responded_messages': responded_messages,
                'missed_messages': missed_messages,
                'unique_clients': unique_clients,
                'avg_response_time': avg_response_time,
                'exceeded_15_min': exceeded_15_min,
                'exceeded_30_min': exceeded_30_min,
                'exceeded_60_min': exceeded_60_min
            } 