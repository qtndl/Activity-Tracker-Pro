from datetime import datetime, timedelta
from sqlalchemy import select, and_, func, or_
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
                        #or_(
                        DBMessage.employee_id == employee_id,
                        #DBMessage.answered_by_employee_id == employee_id,
                        #),
                        DBMessage.received_at >= start_time
                    )
                )
            )
            messages = result.scalars().all()
            
            if not messages:
                return None
            
            # Считаем статистику
            total_messages = len(messages)

            # Сообщения где ЭТОТ сотрудник ответил (answered_by_employee_id == employee_id)
            responded_by_me = [m for m in messages if m.answered_by_employee_id == employee_id]
            responded_messages = len(responded_by_me)

            # Удаленные сообщения не считаются пропущенными
            deleted_messages = len([m for m in messages if m.is_deleted])

            # Сообщения где ответил другой сотрудник (не этот, но кто-то ответил)
            answered_by_others = len([m for m in messages
                                     if m.answered_by_employee_id is not None
                                     and m.answered_by_employee_id != employee_id])

            # Отложенные сообщения не считаются пропущенными
            deferred_messages = len([m for m in messages if m.is_deferred==True and m.answered_by_employee_id==employee_id])

            # Пропущенные = всего - отвечено мной - удалено - отвечено другими - отложенные
            missed_messages = total_messages - (responded_messages+deferred_messages) - deleted_messages - answered_by_others

            # Защита от отрицательных значений
            missed_messages = max(0, missed_messages)

            # Уникальные клиенты (по Telegram ID) - включая всех клиентов
            unique_client_ids = set()
            for msg in messages:
                if msg.client_telegram_id is not None:
                    unique_client_ids.add(msg.client_telegram_id)
            unique_clients = len(unique_client_ids)

            # Время ответа (только для сообщений, где ЭТОТ сотрудник ответил)
            response_times = [m.response_time_minutes for m in responded_by_me if m.response_time_minutes is not None]
            avg_response_time = sum(response_times) / len(response_times) if response_times else None

            # Превышения времени (только для ответов этого сотрудника)

            exceeded_15_min = len([t for t in response_times if t > 15])
            exceeded_30_min = len([t for t in response_times if t > 30])
            exceeded_60_min = len([t for t in response_times if t > 60])

            # Эффективность = (отвечено мной + удалено + отвечено другими) / всего * 100
            # Суть: считаем эффективными все обработанные сообщения, не важно кем
            processed_messages = responded_messages + deleted_messages + answered_by_others
            response_rate = (processed_messages / total_messages * 100) if total_messages > 0 else 0
            efficiency_percent = response_rate
            
            return {
                'total_messages': total_messages-answered_by_others+deferred_messages,
                'responded_messages': responded_messages,
                'deferred_messages': deferred_messages,
                'missed_messages': missed_messages,
                'deleted_messages': deleted_messages,  # Добавляем информацию об удаленных
                'unique_clients': unique_clients,
                'avg_response_time': avg_response_time,
                'exceeded_15_min': exceeded_15_min,
                'exceeded_30_min': exceeded_30_min,
                'exceeded_60_min': exceeded_60_min
            } 