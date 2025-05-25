#!/usr/bin/env python3
"""Единый сервис для вычисления статистики"""

from typing import List, Dict, Optional, Any
from datetime import datetime, date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from dataclasses import dataclass
import logging

from database.models import Employee, Message

logger = logging.getLogger(__name__)

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
        
        period_start, period_end = self._get_period_dates(period) # Определяем период один раз
        logger.info(f"[STAT_DEBUG|get_dashboard_overview] Period: {period}, Start: {period_start}, End: {period_end}, Called for user_id: {user_id}, is_admin: {is_admin}")

        if is_admin:
            # Админ видит общую статистику, посчитанную по УНИКАЛЬНЫМ сообщениям
            
            # 1. Получаем ВСЕ записи Message за период (от всех клиентов, для всех сотрудников)
            all_db_messages_result = await self.db.execute(
                select(Message).where(
                    and_(
                        Message.received_at >= period_start,
                        Message.received_at <= period_end
                    )
                )
            )
            all_db_messages_in_period = all_db_messages_result.scalars().all()
            logger.info(f"[STAT_DEBUG|get_dashboard_overview|Admin] Found {len(all_db_messages_in_period)} DBMessage records in period before grouping.")
            # Логирование деталей каждого сообщения
            for i, msg_debug in enumerate(all_db_messages_in_period):
               logger.info(f"[STAT_DEBUG|get_dashboard_overview|Admin] Msg {i}: id(DB)={msg_debug.id}, chat_id={msg_debug.chat_id}, client_msg_id={msg_debug.message_id}, client_tg_id={msg_debug.client_telegram_id}, emp_id={msg_debug.employee_id}, received={msg_debug.received_at}, answered_by={msg_debug.answered_by_employee_id}")

            # 2. Группируем сообщения по уникальному идентификатору (chat_id, message_id)
            #    message_id здесь это telegram message_id клиента, он одинаков для всех копий этого сообщения у сотрудников.
            unique_client_messages = {}
            for msg in all_db_messages_in_period:
                key = (msg.chat_id, msg.message_id)
                if key not in unique_client_messages:
                    unique_client_messages[key] = []
                unique_client_messages[key].append(msg) # Собираем все копии одного и того же сообщения клиента
            
            # 3. Считаем общие показатели по уникальным клиентским сообщениям
            total_unique_client_messages_count = len(unique_client_messages)
            responded_unique_client_messages_count = 0
            missed_unique_client_messages_count = 0
            deleted_unique_client_messages_count = 0 # Если понадобится
            
            client_ids_for_unique_count = set()
            response_times_for_avg = []

            for client_msg_key, db_message_copies in unique_client_messages.items():
                # db_message_copies - это список всех DBMessage (для разных сотрудников) для одного и того же сообщения клиента
                
                # Добавляем ID клиента для подсчета уникальных клиентов
                if db_message_copies: # Берем из первой копии, они все от одного клиента
                    client_ids_for_unique_count.add(db_message_copies[0].client_telegram_id)

                is_responded_by_anyone = False
                is_deleted_by_anyone = False # Если понадобится трекать удаленные на этом уровне
                
                # Ищем самый ранний ответ на это сообщение среди всех сотрудников
                # и был ли ответ вообще
                earliest_response_time_for_this_message = None
                first_answered_at = None
                first_received_at = db_message_copies[0].received_at # Все копии имеют одно время получения

                for copy in db_message_copies:
                    if copy.answered_by_employee_id is not None and copy.responded_at is not None:
                        is_responded_by_anyone = True
                        if first_answered_at is None or copy.responded_at < first_answered_at:
                            first_answered_at = copy.responded_at
                    if copy.is_deleted:
                        is_deleted_by_anyone = True # Если хотя бы одна копия удалена
                
                if is_responded_by_anyone and first_answered_at is not None:
                    responded_unique_client_messages_count += 1
                    # Рассчитываем время ответа для этого УНИКАЛЬНОГО сообщения
                    # Время ответа должно считаться от received_at до первого responded_at по этому сообщению
                    response_duration_seconds = (first_answered_at - first_received_at).total_seconds()
                    response_times_for_avg.append(response_duration_seconds / 60)

                elif is_deleted_by_anyone: # Если не отвечено, но удалено
                    deleted_unique_client_messages_count += 1 # Считаем отдельно, если нужно
                    # Для общей статистики, если сообщение удалено и не отвечено, оно считается пропущенным.
                    # Это чтобы "В обработке" на диаграмме было 0, если нет реально ожидающих сообщений.
                    missed_unique_client_messages_count +=1
                else: # Не отвечено и не удалено
                    missed_unique_client_messages_count +=1

            # Общее количество уникальных клиентов
            total_unique_clients = len(client_ids_for_unique_count)
            
            # Среднее время ответа (по уникальным отвеченным сообщениям)
            avg_response_time = sum(response_times_for_avg) / len(response_times_for_avg) if response_times_for_avg else 0
            
            # Количество активных сотрудников (можно взять из старой логики, если она корректна)
            active_employees_result = await self.db.execute(select(Employee).where(Employee.is_active == True))
            active_employees_count = len(active_employees_result.scalars().all())
            
            # Срочные сообщения (без ответа более 30 минут) - всегда актуальные (можно использовать старую, если она не зависит от суммирования)
            urgent_messages = await self._get_urgent_messages_count() # Эта функция, вероятно, смотрит на текущие неотвеченные
            
            # Эффективность
            efficiency = 0
            if total_unique_client_messages_count > 0:
                # Эффективность = (отвеченные уникальные / всего уникальных) * 100
                # Не учитываем удаленные как влияющие на общее количество для расчета эффективности, если они не считаются пропущенными
                # То есть, если сообщение было удалено и не отвечено, оно не должно уменьшать эффективность.
                # Поэтому total_for_efficiency = total_unique_client_messages_count - deleted_unique_client_messages_count (если мы их не считаем пропущенными)
                # Но проще: эффективность = отвеченные / (отвеченные + пропущенные)
                denominator_for_efficiency = responded_unique_client_messages_count + missed_unique_client_messages_count
                if denominator_for_efficiency > 0:
                    efficiency = (responded_unique_client_messages_count / denominator_for_efficiency) * 100
            
            return {
                "active_employees": active_employees_count,
                "total_messages_today": total_unique_client_messages_count, # Всего УНИКАЛЬНЫХ сообщений от клиентов
                "responded_today": responded_unique_client_messages_count,    # УНИКАЛЬНЫЕ сообщения, на которые был дан ответ
                "missed_today": missed_unique_client_messages_count,          # УНИКАЛЬНЫЕ сообщения, которые не были отвечены и не удалены
                "unique_clients_today": total_unique_clients,
                "avg_response_time": round(avg_response_time, 1),
                "urgent_messages": urgent_messages, # Эта метрика, вероятно, считается по-другому (не по статистике за период, а по текущему состоянию)
                "efficiency_today": round(efficiency, 1)
            }
        else:
            # Сотрудник видит только свою статистику (использует get_employee_stats, который вызывает _calculate_stats)
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
        """Вычислить статистику по списку сообщений с учетом answered_by_employee_id"""
        
        if not messages:
            return {
                "total_messages": 0,
                "responded_messages": 0,
                "missed_messages": 0,
                "deleted_messages": 0,
                "unique_clients": 0,
                "avg_response_time": None,
                "exceeded_15_min": 0,
                "exceeded_30_min": 0,
                "exceeded_60_min": 0,
                "response_rate": 0,
                "efficiency_percent": 0
            }
        
        # Получаем employee_id первого сообщения (все сообщения одного сотрудника)
        employee_id = messages[0].employee_id
        
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
        
        # Пропущенные = всего - отвечено мной - удалено - отвечено другими
        missed_messages = total_messages - responded_messages - deleted_messages - answered_by_others
        
        # Защита от отрицательных значений
        missed_messages = max(0, missed_messages)
        
        # Уникальные клиенты (по Telegram ID) - включая всех клиентов
        unique_client_ids = set()
        for msg in messages:
            if msg.client_telegram_id is not None:
                unique_client_ids.add(msg.client_telegram_id)
        unique_clients = len(unique_client_ids)
        
        # Время ответа (только для сообщений где ЭТОТ сотрудник ответил)
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
        """Получить количество срочных сообщений (без ответа более 30 минут, исключая удаленные и отвеченные)"""
        
        threshold_time = datetime.utcnow() - timedelta(minutes=30)
        
        result = await self.db.execute(
            select(Message).where(
                and_(
                    Message.answered_by_employee_id.is_(None),  # Никто еще не ответил
                    Message.is_deleted == False,  # Исключаем удаленные сообщения
                    Message.received_at <= threshold_time,
                    Message.message_type == "client"
                )
            )
        )
        return len(result.scalars().all())
    
    async def _get_unanswered_messages_count(self, employee_id: int) -> int:
        """Получить количество неотвеченных сообщений сотрудника (исключая удаленные и отвеченные другими)"""
        
        result = await self.db.execute(
            select(Message).where(
                and_(
                    Message.employee_id == employee_id,
                    Message.answered_by_employee_id.is_(None),  # Никто еще не ответил
                    Message.is_deleted == False,  # Исключаем удаленные сообщения
                    Message.message_type == "client"
                )
            )
        )
        return len(result.scalars().all()) 