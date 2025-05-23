import asyncio
from datetime import datetime, timedelta
from typing import Dict, List
from aiogram import Bot
from sqlalchemy import select
from database.database import AsyncSessionLocal
from database.models import Employee, Message, Notification
from .settings_manager import settings_manager
import logging

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.scheduled_tasks: Dict[int, List[asyncio.Task]] = {}  # message_id: [tasks]
    
    async def schedule_warnings_for_message(self, message_id: int, employee_id: int, chat_id: int):
        """Планирование всех предупреждений для сообщения"""
        # Проверяем включены ли уведомления
        if not await settings_manager.notifications_enabled():
            logger.info("Уведомления отключены в настройках")
            return
        
        # Получаем настройки задержек
        delay1, delay2, delay3 = await settings_manager.get_notification_delays()
        
        # Планируем уведомления
        await self.schedule_warning(message_id, employee_id, chat_id, delay1, "warning_15")
        await self.schedule_warning(message_id, employee_id, chat_id, delay2, "warning_30")
        await self.schedule_warning(message_id, employee_id, chat_id, delay3, "warning_60")
    
    async def schedule_warning(self, message_id: int, employee_id: int, 
                             chat_id: int, delay_minutes: int, notification_type: str):
        """Планирование предупреждения о неотвеченном сообщении"""
        task = asyncio.create_task(
            self._send_delayed_warning(message_id, employee_id, chat_id, delay_minutes, notification_type)
        )
        
        if message_id not in self.scheduled_tasks:
            self.scheduled_tasks[message_id] = []
        
        self.scheduled_tasks[message_id].append(task)
    
    async def _send_delayed_warning(self, message_id: int, employee_id: int, 
                                  chat_id: int, delay_minutes: int, notification_type: str):
        """Отправка отложенного предупреждения"""
        try:
            # Ждем указанное время
            logger.info(f"Запланировано уведомление через {delay_minutes} минут для сообщения {message_id}")
            await asyncio.sleep(delay_minutes * 60)
            
            # Проверяем, было ли сообщение отвечено
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Message).where(Message.id == message_id)
                )
                message = result.scalar_one_or_none()
                
                if message and not message.responded_at:
                    # Получаем информацию о сотруднике
                    emp_result = await session.execute(
                        select(Employee).where(Employee.id == employee_id)
                    )
                    employee = emp_result.scalar_one_or_none()
                    
                    # Отправляем уведомление только активным сотрудникам
                    # Деактивированные = на выходных/в отпуске/на больничном
                    if employee and employee.is_active:
                        # Отправляем уведомление
                        warning_text = self._get_warning_text(delay_minutes, message)
                        
                        try:
                            await self.bot.send_message(
                                employee.telegram_id,
                                warning_text,
                                parse_mode="HTML"
                            )
                            
                            # Сохраняем уведомление в БД
                            notification = Notification(
                                employee_id=employee_id,
                                notification_type=notification_type,
                                message_id=message_id
                            )
                            session.add(notification)
                            await session.commit()
                            
                            logger.info(f"Отправлено уведомление сотруднику {employee_id} через {delay_minutes} мин")
                            
                        except Exception as e:
                            logger.error(f"Не удалось отправить уведомление сотруднику {employee_id}: {e}")
                    else:
                        if employee and not employee.is_active:
                            logger.info(f"Сотрудник {employee_id} деактивирован (выходной/отпуск) - уведомление не отправлено")
                else:
                    if message and message.responded_at:
                        logger.info(f"Сообщение {message_id} уже отвечено - уведомление отменено")
        
        except asyncio.CancelledError:
            # Задача была отменена (сообщение было отвечено)
            logger.info(f"Уведомление для сообщения {message_id} отменено")
            pass
        
        finally:
            # Удаляем задачу из списка
            if message_id in self.scheduled_tasks:
                self.scheduled_tasks[message_id] = [
                    t for t in self.scheduled_tasks[message_id] if not t.done()
                ]
    
    async def cancel_notifications(self, message_id: int):
        """Отмена всех запланированных уведомлений для сообщения"""
        if message_id in self.scheduled_tasks:
            for task in self.scheduled_tasks[message_id]:
                if not task.done():
                    task.cancel()
            
            del self.scheduled_tasks[message_id]
    
    def _get_warning_text(self, delay_minutes: int, message: Message) -> str:
        """Генерация текста предупреждения"""
        client_info = f"@{message.client_username}" if message.client_username else message.client_name
        
        # Выбираем emoji в зависимости от времени
        if delay_minutes <= 5:
            emoji = "⚠️"
        elif delay_minutes <= 15:
            emoji = "🚨"
        else:
            emoji = "🔴"
        
        # Формируем правильный текст времени
        if delay_minutes == 1:
            urgency = "1 минуту"
        elif delay_minutes < 5:
            urgency = f"{delay_minutes} минуты"
        elif delay_minutes < 60:
            urgency = f"{delay_minutes} минут"
        elif delay_minutes == 60:
            urgency = "1 час"
        else:
            hours = delay_minutes // 60
            minutes = delay_minutes % 60
            if minutes == 0:
                urgency = f"{hours} час{'а' if hours < 5 else 'ов'}"
            else:
                urgency = f"{hours} час{'а' if hours < 5 else 'ов'} {minutes} мин"
        
        text = f"{emoji} <b>Внимание!</b>\n\n"
        text += f"Вы не ответили на сообщение от {client_info} уже <b>{urgency}</b>!\n"
        text += f"Чат ID: <code>{message.chat_id}</code>\n"
        
        if message.message_text:
            preview = message.message_text[:100] + "..." if len(message.message_text) > 100 else message.message_text
            text += f"\nТекст сообщения:\n<i>{preview}</i>"
        
        return text
    
    async def send_daily_report(self, employee_id: int, stats):
        """Отправка ежедневного отчета сотруднику"""
        # Проверяем включены ли ежедневные отчеты
        if not await settings_manager.daily_reports_enabled():
            logger.info("Ежедневные отчеты отключены в настройках")
            return
            
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Employee).where(Employee.id == employee_id)
            )
            employee = result.scalar_one_or_none()
            
            # Отправляем отчеты только активным сотрудникам
            if not employee or not employee.is_active:
                if employee and not employee.is_active:
                    logger.info(f"Сотрудник {employee_id} деактивирован - ежедневный отчет не отправлен")
                return
            
            text = "📊 <b>Ваша статистика за сегодня:</b>\n\n"
            text += f"📨 Всего сообщений: {stats.total_messages}\n"
            text += f"✅ Отвечено: {stats.responded_messages}\n"
            text += f"❌ Пропущено: {stats.missed_messages}\n"
            
            if stats.responded_messages > 0:
                text += f"\n⏱ Среднее время ответа: {stats.avg_response_time:.1f} мин\n"
                
                if stats.exceeded_15_min > 0:
                    text += f"\n⚠️ Превышений времени ответа:\n"
                    text += f"  • Более 15 мин: {stats.exceeded_15_min}\n"
                    text += f"  • Более 30 мин: {stats.exceeded_30_min}\n"
                    text += f"  • Более 1 часа: {stats.exceeded_60_min}\n"
            
            # Добавляем оценку работы
            if stats.missed_messages == 0 and stats.avg_response_time < 15:
                text += "\n🌟 Отличная работа! Продолжайте в том же духе!"
            elif stats.missed_messages > 0:
                text += f"\n⚠️ Обратите внимание на пропущенные сообщения!"
            
            try:
                await self.bot.send_message(
                    employee.telegram_id,
                    text,
                    parse_mode="HTML"
                )
                logger.info(f"Отправлен ежедневный отчет сотруднику {employee_id}")
            except Exception as e:
                logger.error(f"Не удалось отправить ежедневный отчет сотруднику {employee_id}: {e}")
    
    async def send_admin_report(self, admin_id: int, all_stats):
        """Отправка отчета администратору"""
        # Проверяем включены ли ежедневные отчеты
        if not await settings_manager.daily_reports_enabled():
            logger.info("Ежедневные отчеты отключены - отчет админу не отправлен")
            return
            
        text = "📊 <b>Общая статистика по всем сотрудникам:</b>\n\n"
        
        total_messages = sum(s.total_messages for s in all_stats)
        total_responded = sum(s.responded_messages for s in all_stats)
        total_missed = sum(s.missed_messages for s in all_stats)
        
        text += f"📨 Всего сообщений: {total_messages}\n"
        text += f"✅ Отвечено: {total_responded}\n"
        text += f"❌ Пропущено: {total_missed}\n"
        
        if total_responded > 0:
            avg_response = sum(s.avg_response_time * s.responded_messages for s in all_stats) / total_responded
            text += f"⏱ Средний ответ: {avg_response:.1f} мин\n"
        
        text += "\n<b>По сотрудникам:</b>\n"
        
        for stat in all_stats:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Employee).where(Employee.id == stat.employee_id)
                )
                employee = result.scalar_one_or_none()
                
                if employee:
                    status_emoji = "✅" if employee.is_active else "💤"
                    status_text = "активен" if employee.is_active else "деактивирован"
                    
                    text += f"\n{status_emoji} {employee.full_name} ({status_text}):\n"
                    text += f"  • Сообщений: {stat.total_messages}\n"
                    text += f"  • Пропущено: {stat.missed_messages}\n"
                    if stat.responded_messages > 0:
                        text += f"  • Среднее время: {stat.avg_response_time:.1f} мин\n"
        
        try:
            await self.bot.send_message(
                admin_id,
                text,
                parse_mode="HTML"
            )
            logger.info(f"Отправлен отчет администратору {admin_id}")
        except Exception as e:
            logger.error(f"Не удалось отправить отчет администратору: {e}") 