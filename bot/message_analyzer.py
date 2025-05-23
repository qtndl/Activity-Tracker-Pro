"""Модуль для анализа сообщений и определения адресатов"""

import re
from typing import List, Optional, Dict, Any
from datetime import datetime
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import Employee, ChatEmployee
import logging

logger = logging.getLogger(__name__)


class MessageAnalyzer:
    """Анализатор сообщений для определения адресатов и типа сообщения"""
    
    def __init__(self):
        pass
    
    async def analyze_message(self, message: Message, db: AsyncSession) -> Dict[str, Any]:
        """
        Анализирует сообщение и возвращает информацию об адресате
        
        Returns:
            {
                'is_from_client': bool,  # Сообщение от клиента
                'is_response': bool,     # Ответ сотрудника
                'addressed_to_employee_id': int|None,  # ID конкретного адресата
                'is_addressed_to_specific': bool,  # Адресовано конкретно
                'target_employees': List[int],  # Список ID сотрудников для уведомлений
                'reply_to_message_id': int|None,  # ID сообщения на которое отвечают
                'message_type': str  # 'client' или 'employee_response'
            }
        """
        
        result = {
            'is_from_client': False,
            'is_response': False, 
            'addressed_to_employee_id': None,
            'is_addressed_to_specific': False,
            'target_employees': [],
            'reply_to_message_id': None,
            'message_type': 'client'
        }
        
        # Получаем всех сотрудников в системе
        employees_result = await db.execute(select(Employee))
        all_employees = employees_result.scalars().all()
        employee_by_telegram_id = {emp.telegram_id: emp for emp in all_employees}
        employee_by_username = {emp.telegram_username.lower(): emp for emp in all_employees if emp.telegram_username}
        
        sender_telegram_id = message.from_user.id
        sender_username = message.from_user.username
        
        # Проверяем, является ли отправитель сотрудником
        sender_employee = employee_by_telegram_id.get(sender_telegram_id)
        
        if sender_employee:
            # Сообщение от сотрудника - проверяем, является ли ответом
            result['message_type'] = 'employee_response'
            
            if message.reply_to_message:
                # Это ответ на конкретное сообщение
                result['is_response'] = True
                result['reply_to_message_id'] = message.reply_to_message.message_id
                logger.info(f"Сотрудник {sender_employee.full_name} ответил на сообщение {message.reply_to_message.message_id}")
            else:
                # Просто сообщение сотрудника, не ответ
                logger.info(f"Сотрудник {sender_employee.full_name} написал сообщение (не ответ)")
                
        else:
            # Сообщение от клиента
            result['is_from_client'] = True
            result['message_type'] = 'client'
            
            # Анализируем кому адресовано сообщение
            addressed_to = await self._analyze_addressing(message, employee_by_username, db)
            
            if addressed_to:
                # Сообщение адресовано конкретному сотруднику
                result['addressed_to_employee_id'] = addressed_to.id
                result['is_addressed_to_specific'] = True
                result['target_employees'] = [addressed_to.id]
                logger.info(f"Клиент обратился к {addressed_to.full_name}")
            else:
                # Сообщение без конкретного адресата - уведомляем всех активных в чате
                active_employees = await self._get_active_employees_in_chat(message.chat.id, db)
                result['target_employees'] = [emp.id for emp in active_employees]
                logger.info(f"Общее сообщение клиента, уведомляем {len(result['target_employees'])} сотрудников")
        
        return result
    
    async def _analyze_addressing(self, message: Message, employee_by_username: Dict[str, Employee], db: AsyncSession) -> Optional[Employee]:
        """Анализирует к кому обращено сообщение"""
        
        if not message.text:
            return None
        
        text = message.text.lower()
        
        # 1. Проверяем упоминания @username
        mentions = re.findall(r'@(\w+)', text)
        for mention in mentions:
            employee = employee_by_username.get(mention.lower())
            if employee:
                return employee
        
        # 2. Проверяем ответ на сообщение (reply)
        if message.reply_to_message:
            replied_user_id = message.reply_to_message.from_user.id
            
            # Ищем сотрудника по Telegram ID
            employees_result = await db.execute(
                select(Employee).where(Employee.telegram_id == replied_user_id)
            )
            employee = employees_result.scalar_one_or_none()
            if employee:
                return employee
        
        # 3. Анализируем обращения по имени (простая эвристика)
        # Можно добавить более сложную логику анализа имен
        
        return None
    
    async def _get_active_employees_in_chat(self, chat_id: int, db: AsyncSession) -> List[Employee]:
        """Получает список активных сотрудников в чате"""
        
        # Получаем активных сотрудников, которые есть в этом чате
        result = await db.execute(
            select(Employee, ChatEmployee)
            .join(ChatEmployee, Employee.id == ChatEmployee.employee_id)
            .where(
                ChatEmployee.chat_id == chat_id,
                Employee.is_active == True,
                ChatEmployee.is_active_in_chat == True
            )
        )
        
        employees = [row[0] for row in result.fetchall()]
        
        # Если нет записей в ChatEmployee, считаем что все активные сотрудники могут получать уведомления
        if not employees:
            result = await db.execute(
                select(Employee).where(Employee.is_active == True)
            )
            employees = result.scalars().all()
            logger.info(f"Нет записей ChatEmployee для чата {chat_id}, используем всех активных сотрудников")
        
        return employees
    
    async def update_employee_chat_activity(self, employee_id: int, chat_id: int, db: AsyncSession):
        """Обновляет активность сотрудника в чате"""
        
        # Ищем существующую запись
        result = await db.execute(
            select(ChatEmployee).where(
                ChatEmployee.employee_id == employee_id,
                ChatEmployee.chat_id == chat_id
            )
        )
        chat_employee = result.scalar_one_or_none()
        
        if chat_employee:
            # Обновляем время последней активности
            chat_employee.last_seen_at = datetime.utcnow()
            chat_employee.is_active_in_chat = True
        else:
            # Создаем новую запись
            chat_employee = ChatEmployee(
                employee_id=employee_id,
                chat_id=chat_id,
                is_active_in_chat=True,
                last_seen_at=datetime.utcnow()
            )
            db.add(chat_employee)
        
        await db.commit()


# Глобальный экземпляр анализатора
message_analyzer = MessageAnalyzer() 