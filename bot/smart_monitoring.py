"""Умный сервис мониторинга сообщений с поддержкой адресации и ответов"""

from datetime import datetime
from typing import List, Dict, Any
from aiogram.types import Message as TelegramMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.database import AsyncSessionLocal
from database.models import Message, Employee, ChatEmployee
from .message_analyzer import message_analyzer
from .notifications import NotificationService
import logging

logger = logging.getLogger(__name__)


class SmartMonitoringService:
    """Умный сервис мониторинга с поддержкой адресации"""
    
    def __init__(self, notification_service: NotificationService):
        self.notification_service = notification_service
    
    async def process_message(self, telegram_message: TelegramMessage):
        """Обрабатывает входящее сообщение с умной логикой"""
        
        async with AsyncSessionLocal() as db:
            try:
                # Анализируем сообщение
                analysis = await message_analyzer.analyze_message(telegram_message, db)
                
                logger.info(f"Анализ сообщения: {analysis}")
                
                if analysis['is_from_client']:
                    # Сообщение от клиента - создаем записи и планируем уведомления
                    await self._handle_client_message(telegram_message, analysis, db)
                    
                elif analysis['is_response']:
                    # Ответ сотрудника - отмечаем сообщение как отвеченное
                    await self._handle_employee_response(telegram_message, analysis, db)
                
                else:
                    # Обычное сообщение сотрудника - обновляем активность в чате
                    await self._handle_employee_activity(telegram_message, db)
                    
            except Exception as e:
                logger.error(f"Ошибка при обработке сообщения: {e}")
    
    async def _handle_client_message(self, telegram_message: TelegramMessage, analysis: Dict[str, Any], db: AsyncSession):
        """Обрабатывает сообщение от клиента"""
        
        if analysis['is_addressed_to_specific']:
            # Сообщение адресовано конкретному сотруднику
            await self._create_targeted_message(telegram_message, analysis, db)
        else:
            # Общее сообщение - создаем записи для всех активных сотрудников
            await self._create_broadcast_messages(telegram_message, analysis, db)
    
    async def _create_targeted_message(self, telegram_message: TelegramMessage, analysis: Dict[str, Any], db: AsyncSession):
        """Создает сообщение адресованное конкретному сотруднику"""
        
        employee_id = analysis['addressed_to_employee_id']
        # Формируем имя клиента
        client_name = ((telegram_message.from_user.first_name or '') +
                      (' ' + telegram_message.from_user.last_name if telegram_message.from_user.last_name else '')).strip() or None
        client_username = telegram_message.from_user.username
        
        # Создаем запись сообщения
        message = Message(
            employee_id=employee_id,
            chat_id=telegram_message.chat.id,
            message_id=telegram_message.message_id,
            client_telegram_id=telegram_message.from_user.id,
            client_username=client_username,
            client_name=client_name,
            message_text=telegram_message.text,
            received_at=datetime.utcnow(),
            addressed_to_employee_id=employee_id,
            is_addressed_to_specific=True,
            message_type="client"
        )
        
        db.add(message)
        await db.commit()
        await db.refresh(message)
        
        # Планируем уведомления только для этого сотрудника
        await self.notification_service.schedule_warnings_for_message(
            message.id, employee_id, telegram_message.chat.id
        )
        
        logger.info(f"Создано адресное сообщение {message.id} для сотрудника {employee_id}")
    
    async def _create_broadcast_messages(self, telegram_message: TelegramMessage, analysis: Dict[str, Any], db: AsyncSession):
        """Создает сообщения для всех активных сотрудников"""
        
        target_employees = analysis['target_employees']
        
        if not target_employees:
            logger.warning(f"Нет активных сотрудников для уведомления в чате {telegram_message.chat.id}")
            return
        
        created_messages = []
        
        # Формируем имя клиента
        client_name = ((telegram_message.from_user.first_name or '') +
                      (' ' + telegram_message.from_user.last_name if telegram_message.from_user.last_name else '')).strip() or None
        client_username = telegram_message.from_user.username
        
        for employee_id in target_employees:
            # Создаем отдельную запись для каждого сотрудника
            message = Message(
                employee_id=employee_id,
                chat_id=telegram_message.chat.id,
                message_id=telegram_message.message_id,
                client_telegram_id=telegram_message.from_user.id,
                client_username=client_username,
                client_name=client_name,
                message_text=telegram_message.text,
                received_at=datetime.utcnow(),
                is_addressed_to_specific=False,
                message_type="client"
            )
            
            db.add(message)
            created_messages.append((message, employee_id))
        
        await db.commit()
        
        # Планируем уведомления для каждого сотрудника
        for message, employee_id in created_messages:
            await db.refresh(message)
            await self.notification_service.schedule_warnings_for_message(
                message.id, employee_id, telegram_message.chat.id
            )
        
        logger.info(f"Создано {len(created_messages)} общих сообщений для чата {telegram_message.chat.id}")
    
    async def _handle_employee_response(self, telegram_message: TelegramMessage, analysis: Dict[str, Any], db: AsyncSession):
        """Обрабатывает ответ сотрудника"""
        
        reply_to_message_id = analysis['reply_to_message_id']
        sender_telegram_id = telegram_message.from_user.id
        
        # Находим сотрудника
        emp_result = await db.execute(
            select(Employee).where(Employee.telegram_id == sender_telegram_id)
        )
        employee = emp_result.scalar_one_or_none()
        
        if not employee:
            return
        
        # 1. Сначала находим сообщение, на которое отвечают, чтобы определить клиента
        replied_message_result = await db.execute(
            select(Message).where(
                Message.employee_id == employee.id,
                Message.chat_id == telegram_message.chat.id,
                Message.message_id == reply_to_message_id,
                Message.message_type == "client"
            )
        )
        replied_message = replied_message_result.scalar_one_or_none()
        
        if not replied_message:
            logger.info(f"Не найдено исходное сообщение для reply {reply_to_message_id}")
            return
        
        client_telegram_id = replied_message.client_telegram_id
        if not client_telegram_id:
            logger.info(f"У сообщения {reply_to_message_id} нет ID клиента")
            return
        
        # 2. Теперь находим ВСЕ неотвеченные сообщения от этого клиента для данного сотрудника
        all_messages_result = await db.execute(
            select(Message).where(
                Message.employee_id == employee.id,
                Message.chat_id == telegram_message.chat.id,
                Message.client_telegram_id == client_telegram_id,
                Message.responded_at.is_(None),
                Message.message_type == "client"
            ).order_by(Message.received_at)  # Сортируем по времени для логирования
        )
        
        messages_to_update = all_messages_result.scalars().all()
        
        if not messages_to_update:
            logger.info(f"Нет неотвеченных сообщений от клиента {client_telegram_id}")
            return
        
        response_time = datetime.utcnow()
        updated_count = 0
        
        for message in messages_to_update:
            # Отмечаем сообщение как отвеченное
            message.responded_at = response_time
            
            # Вычисляем время ответа ИНДИВИДУАЛЬНО для каждого сообщения
            time_diff = message.responded_at - message.received_at
            message.response_time_minutes = time_diff.total_seconds() / 60
            
            # Отменяем запланированные уведомления для каждого сообщения
            await self.notification_service.cancel_notifications(message.id)
            
            updated_count += 1
            logger.info(f"Сообщение {message.id} отмечено как отвеченное (время ответа: {message.response_time_minutes:.1f} мин)")
        
        logger.info(f"Ответ сотрудника {employee.full_name} закрыл {updated_count} сообщений от клиента {client_telegram_id}")
        
        # Обновляем активность сотрудника в чате
        await message_analyzer.update_employee_chat_activity(employee.id, telegram_message.chat.id, db)
        
        await db.commit()
    
    async def _handle_employee_activity(self, telegram_message: TelegramMessage, db: AsyncSession):
        """Обрабатывает активность сотрудника в чате"""
        
        sender_telegram_id = telegram_message.from_user.id
        
        # Находим сотрудника
        emp_result = await db.execute(
            select(Employee).where(Employee.telegram_id == sender_telegram_id)
        )
        employee = emp_result.scalar_one_or_none()
        
        if employee:
            # Обновляем активность в чате
            await message_analyzer.update_employee_chat_activity(
                employee.id, telegram_message.chat.id, db
            )
            logger.info(f"Обновлена активность сотрудника {employee.full_name} в чате {telegram_message.chat.id}")
    
    async def get_chat_statistics(self, chat_id: int) -> Dict[str, Any]:
        """Получает статистику по чату"""
        
        async with AsyncSessionLocal() as db:
            # Статистика сообщений
            messages_result = await db.execute(
                select(Message).where(
                    Message.chat_id == chat_id,
                    Message.message_type == "client"
                )
            )
            messages = messages_result.scalars().all()
            
            total_messages = len(messages)
            responded_messages = len([m for m in messages if m.responded_at])
            missed_messages = len([m for m in messages if not m.responded_at])
            
            # Активные сотрудники в чате
            employees_result = await db.execute(
                select(Employee, ChatEmployee)
                .join(ChatEmployee, Employee.id == ChatEmployee.employee_id)
                .where(
                    ChatEmployee.chat_id == chat_id,
                    ChatEmployee.is_active_in_chat == True
                )
            )
            
            active_employees = [row[0] for row in employees_result.fetchall()]
            
            return {
                'chat_id': chat_id,
                'total_messages': total_messages,
                'responded_messages': responded_messages,
                'missed_messages': missed_messages,
                'active_employees': len(active_employees),
                'response_rate': (responded_messages / total_messages * 100) if total_messages > 0 else 0
            } 