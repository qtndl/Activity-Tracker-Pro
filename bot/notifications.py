import asyncio
from datetime import datetime, timedelta
from typing import Dict, List
from aiogram import Bot
from sqlalchemy import select
from database.database import AsyncSessionLocal
from database.models import Employee, Message, Notification
from .settings_manager import settings_manager
from web.services.statistics_service import EmployeeStats
import logging

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.scheduled_tasks: Dict[int, List[asyncio.Task]] = {}  # message_id (DBMessage.id): [tasks]
    
    async def schedule_warnings_for_message(self, message_id: int, employee_id: int, chat_id: int):
        """Планирование всех предупреждений для сообщения (DBMessage.id)"""
        logger.info(f"[TASK_CREATE_INIT] Инициировано планирование для DBMessage.id={message_id}, Employee.id={employee_id}")
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
        """Планирование предупреждения о неотвеченном сообщении (DBMessage.id)"""
        logger.info(f"[TASK_CREATE_SCHEDULE] Планирование задачи для DBMessage.id={message_id}, Employee.id={employee_id}, Delay={delay_minutes}m, Type={notification_type}")
        task = asyncio.create_task(
            self._send_delayed_warning(message_id, employee_id, chat_id, delay_minutes, notification_type)
        )
        
        if message_id not in self.scheduled_tasks:
            self.scheduled_tasks[message_id] = []
        
        self.scheduled_tasks[message_id].append(task)
    
    async def _send_delayed_warning(self, message_id: int, employee_id: int, 
                                  chat_id: int, delay_minutes: int, notification_type: str):
        """Отправка отложенного предупреждения (DBMessage.id)"""
        task_id = id(asyncio.current_task()) # Получаем ID текущей задачи asyncio
        logger.info(f"[TASK_START] DBMessage.id={message_id}, Employee.id={employee_id}, TaskID={task_id}, Delay={delay_minutes}m, Type={notification_type} - Ожидание {delay_minutes*60} сек.")
        try:
            # Ждем указанное время
            await asyncio.sleep(delay_minutes * 60)
            
            logger.info(f"[TASK_AWAKE] DBMessage.id={message_id}, Employee.id={employee_id}, TaskID={task_id} - Проснулся после ожидания. Проверка статуса сообщения.")
            
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
                            
                            logger.info(f"[TASK_SENT] DBMessage.id={message_id}, Employee.id={employee_id}, TaskID={task_id} - Уведомление отправлено.")
                            
                        except Exception as e:
                            logger.error(f"[TASK_ERROR_SEND] DBMessage.id={message_id}, Employee.id={employee_id}, TaskID={task_id} - Не удалось отправить: {e}")
                    else:
                        if employee and not employee.is_active:
                            logger.info(f"[TASK_INACTIVE_EMP] DBMessage.id={message_id}, Employee.id={employee_id}, TaskID={task_id} - Сотрудник неактивен.")
                        elif not employee:
                            logger.info(f"[TASK_NO_EMP] DBMessage.id={message_id}, TaskID={task_id} - Сотрудник не найден для Employee.id={employee_id}.")
                else:
                    if message and message.responded_at:
                        logger.info(f"[TASK_ALREADY_RESPONDED] DBMessage.id={message_id}, TaskID={task_id} - Сообщение уже отвечено, уведомление не нужно.")
                    elif not message:
                        logger.info(f"[TASK_NO_MESSAGE] DBMessage.id={message_id}, TaskID={task_id} - Сообщение не найдено в БД, отмена уведомления.")
        
        except asyncio.CancelledError:
            logger.info(f"[TASK_CANCELLED_EXCEPTION] DBMessage.id={message_id}, TaskID={task_id} - Задача отменена через исключение.")
            pass
        
        finally:
            logger.info(f"[TASK_FINALLY] DBMessage.id={message_id}, TaskID={task_id} - Вход в блок finally.")
            # Удаляем задачу из списка
            if message_id in self.scheduled_tasks:
                original_task_count = len(self.scheduled_tasks[message_id])
                self.scheduled_tasks[message_id] = [
                    t for t in self.scheduled_tasks[message_id] if not t.done()
                ]
                new_task_count = len(self.scheduled_tasks[message_id])
                logger.info(f"[TASK_FINALLY_CLEANUP] DBMessage.id={message_id}, TaskID={task_id} - Задач было: {original_task_count}, стало: {new_task_count}. Текущая задача {'выполнена' if asyncio.current_task().done() else 'НЕ выполнена'}.")
                if not self.scheduled_tasks[message_id]:
                    del self.scheduled_tasks[message_id]
                    logger.info(f"[TASK_FINALLY_DELETED_KEY] DBMessage.id={message_id}, TaskID={task_id} - Ключ удален из scheduled_tasks.")
            else:
                logger.warning(f"[TASK_FINALLY_NO_KEY] DBMessage.id={message_id}, TaskID={task_id} - Ключ уже отсутствует в scheduled_tasks.")
    
    async def cancel_notifications(self, message_id: int):
        """Отмена всех запланированных уведомлений для сообщения (DBMessage.id)"""
        logger.info(f"[TASK_CANCEL_INIT] Инициирована отмена для DBMessage.id={message_id}")
        if message_id in self.scheduled_tasks:
            tasks_to_cancel = self.scheduled_tasks[message_id]
            logger.info(f"[TASK_CANCEL_FOUND] DBMessage.id={message_id} - Найдено {len(tasks_to_cancel)} задач для отмены.")
            for task_index, task in enumerate(tasks_to_cancel):
                task_id = id(task)
                if not task.done():
                    task.cancel()
                    logger.info(f"[TASK_CANCEL_ATTEMPT] DBMessage.id={message_id}, TaskIndex={task_index}, TaskID={task_id} - Вызван cancel().")
                else:
                    logger.info(f"[TASK_CANCEL_ALREADY_DONE] DBMessage.id={message_id}, TaskIndex={task_index}, TaskID={task_id} - Задача уже выполнена, не отменяем.")
            
            # Важно: НЕ удаляем ключ self.scheduled_tasks[message_id] здесь.
            # Блок finally в _send_delayed_warning сам очистит этот список и ключ, когда все задачи завершатся.
            # Если удалить здесь, а задачи еще выполняют finally, будет ошибка.
        else:
            logger.info(f"[TASK_CANCEL_NOT_FOUND] DBMessage.id={message_id} - Задачи для отмены не найдены (ключ отсутствует).")
    
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
    
    async def send_daily_report(self, employee_id: int, stats_obj: EmployeeStats):
        """Отправка ежедневного отчета сотруднику (принимает объект EmployeeStats)"""
        # Проверяем включены ли ежедневные отчеты
        if not await settings_manager.daily_reports_enabled():
            logger.info(f"Ежедневные отчеты отключены - отчет сотруднику {employee_id} не отправлен")
            return
        
        # Получаем данные из объекта EmployeeStats
        total_messages = stats_obj.total_messages
        responded_messages = stats_obj.responded_messages
        missed_messages = stats_obj.missed_messages
        deleted_messages = stats_obj.deleted_messages
        unique_clients = stats_obj.unique_clients
        avg_response_time = stats_obj.avg_response_time # Может быть None
        exceeded_15_min = stats_obj.exceeded_15_min
        exceeded_30_min = stats_obj.exceeded_30_min
        exceeded_60_min = stats_obj.exceeded_60_min

        text = "📊 <b>Ваша статистика за сегодня:</b>\n\n"
        text += f"📨 Всего сообщений: {total_messages}\n"
        text += f"✅ Отвечено: {responded_messages}\n"
        text += f"❌ Пропущено: {missed_messages}\n"
        
        if deleted_messages > 0:
            text += f"🗑 Удалено клиентами: {deleted_messages}\n"
        
        text += f"👥 Уникальных клиентов: {unique_clients}\n"
        
        if avg_response_time is not None and responded_messages > 0: # Отображаем только если есть ответы
            text += f"\n⏱ Среднее время ответа: {avg_response_time:.1f} мин\n"
            
            if exceeded_15_min > 0 or exceeded_30_min > 0 or exceeded_60_min > 0:
                text += f"\n⚠️ Превышений времени ответа:\n"
                if exceeded_15_min > 0: text += f"  • Более 15 мин: {exceeded_15_min}\n"
                if exceeded_30_min > 0: text += f"  • Более 30 мин: {exceeded_30_min}\n"
                if exceeded_60_min > 0: text += f"  • Более 1 часа: {exceeded_60_min}\n"
        elif responded_messages == 0:
            text += f"\n⏱ Среднее время ответа: - (нет ответов)\n"
        
        # Добавляем оценку работы
        if missed_messages == 0 and responded_messages > 0 and (avg_response_time is None or avg_response_time < 15):
            text += "\n🌟 Отличная работа! Продолжайте в том же духе!"
        elif missed_messages > 0:
            text += f"\n⚠️ Обратите внимание на пропущенные сообщения!"
        
        if deleted_messages > 0:
            text += f"\n\n💡 <i>Удаленные клиентами сообщения не считаются пропущенными</i>"
        
        # Получаем telegram_id сотрудника для отправки
        employee_telegram_id = None
        async with AsyncSessionLocal() as session:
            employee_obj = await session.get(Employee, employee_id)
            if employee_obj:
                employee_telegram_id = employee_obj.telegram_id
            else:
                logger.error(f"Не найден сотрудник с ID {employee_id} для отправки ежедневного отчета.")
                return

        if employee_telegram_id:
            try:
                await self.bot.send_message(
                    employee_telegram_id,
                    text,
                    parse_mode="HTML"
                )
                logger.info(f"Отправлен ежедневный отчет сотруднику {employee_id}")
            except Exception as e:
                logger.error(f"Не удалось отправить ежедневный отчет сотруднику {employee_id} (Telegram ID: {employee_telegram_id}): {e}")
        else:
            logger.error(f"Не удалось получить Telegram ID для сотрудника {employee_id}. Отчет не отправлен.")
    
    async def send_admin_report(self, admin_telegram_id: int, summary_stats: dict, individual_employee_stats: List[EmployeeStats]):
        """Отправка отчета администратору.
        summary_stats: dict - общая статистика из get_dashboard_overview.
        individual_employee_stats: List[EmployeeStats] - список статистики по каждому сотруднику.
        """
        if not await settings_manager.daily_reports_enabled():
            logger.info(f"Ежедневные отчеты отключены - отчет админу {admin_telegram_id} не отправлен")
            return
            
        text = "📊 <b>Общая статистика по всем сотрудникам:</b>\n\n"

        # Используем данные из summary_stats (уже корректно посчитаны)
        text += f"📨 Всего сообщений: {summary_stats.get('total_messages_today', 0)}\n"
        text += f"✅ Отвечено: {summary_stats.get('responded_today', 0)}\n"
        text += f"❌ Пропущено: {summary_stats.get('missed_today', 0)}\n"
        text += f"👥 Уникальных клиентов: {summary_stats.get('unique_clients_today', 0)}\n"

        avg_response_time_admin = summary_stats.get('avg_response_time', 0)
        text += f"⏱ Средний ответ: {avg_response_time_admin:.1f} мин\n"
        text += f"📈 Эффективность: {summary_stats.get('efficiency_today', 0):.1f}%\n" # Добавлено

        text += "\n<b>По сотрудникам:</b>\n"

        if not individual_employee_stats:
            text += "\n<i>Нет данных по сотрудникам для отображения.</i>"
        else:
            for stats_obj in individual_employee_stats: # Теперь это список объектов EmployeeStats
                status_emoji = "✅" if stats_obj.is_active else "💤"
                status_text = "активен" if stats_obj.is_active else "деактивирован"
                    
                text += f"\n{status_emoji} {stats_obj.employee_name} ({status_text}):\n"
                text += f"  • Сообщений: {stats_obj.total_messages}\n"
                # Отвечено этим сотрудником
                text += f"  • Отвечено им: {stats_obj.responded_messages}\n" 
                text += f"  • Пропущено им: {stats_obj.missed_messages}\n"
                text += f"  • Уникальных клиентов: {stats_obj.unique_clients}\n"
                if stats_obj.avg_response_time is not None and stats_obj.responded_messages > 0:
                    text += f"  • Среднее время (его ответов): {stats_obj.avg_response_time:.1f} мин\n"
                elif stats_obj.responded_messages == 0:
                    text += f"  • Среднее время (его ответов): - (нет ответов)\n"

        try:
            await self.bot.send_message(
                admin_telegram_id,
                text,
                parse_mode="HTML"
            )
            logger.info(f"Отправлен отчет администратору {admin_telegram_id}")
        except Exception as e:
            logger.error(f"Не удалось отправить отчет администратору {admin_telegram_id}: {e}") 