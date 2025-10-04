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
import pytz

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.scheduled_tasks: Dict[int, List[asyncio.Task]] = {}  # message_id (DBMessage.id): [tasks]
    
    async def schedule_warnings_for_message(self, message_id: int, employee_id: int, chat_id: int):
        delay_data = await settings_manager.get_notification_delays()
        # print(f'delay_data={delay_data[0]}')
        if delay_data[0] == 'False':
            next_working_hour = await self.get_next_9am_moscow_utc()
            async with AsyncSessionLocal() as session:
                db_message = await session.execute(select(Message).where(Message.id == message_id))
                db_msg = db_message.scalar_one_or_none()
                if db_msg:
                    db_msg.received_at = next_working_hour
                    await session.commit()

        delays = delay_data[1:]
        # print(f'delays={delays}')
        types = ["warning_15", "warning_30", "warning_60"]
        logger.info(f"[NOTIFY] Планирование уведомлений: DBMessage={message_id}, Employee={employee_id}, Delays={delays}m, Types={types}")
        if not await settings_manager.notifications_enabled():
            logger.info("[NOTIFY] Уведомления отключены в настройках")
            return
        for delay, ntype in zip(delays, types):
            # print(f'delay={delay}')
            await self.schedule_warning(message_id, employee_id, chat_id, delay, ntype)
    
    async def schedule_warning(self, message_id: int, employee_id: int, chat_id: int, delay_minutes: int, notification_type: str):
        task = asyncio.create_task(
            self._send_delayed_warning(message_id, employee_id, chat_id, delay_minutes, notification_type)
        )
        if message_id not in self.scheduled_tasks:
            self.scheduled_tasks[message_id] = []
        self.scheduled_tasks[message_id].append(task)
    
    async def _send_delayed_warning(self, message_id: int, employee_id: int, chat_id: int, delay_minutes: int, notification_type: str):
        # Группируем логи ожидания по DBMessage и Employee
        print(f'delay_minutes = {delay_minutes}')
        if delay_minutes == 1:
            logger.info(f"[NOTIFY] Ожидание: DBMessage={message_id}, Employee={employee_id}, Delays=[1m, 2m, 60m], Types=[warning_15, warning_30, warning_60]")
        try:
            await asyncio.sleep(delay_minutes)
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(Message).where(Message.id == message_id))
                message = result.scalar_one_or_none()
                if message and not message.responded_at and not message.is_deferred:
                    emp_result = await session.execute(select(Employee).where(Employee.id == employee_id))
                    employee = emp_result.scalar_one_or_none()
                    if employee and employee.is_active:
                        warning_text = await self._get_warning_text(delay_minutes, message)
                        try:
                            await self.bot.send_message(employee.telegram_id, warning_text, parse_mode="HTML")
                            notification = Notification(employee_id=employee_id, notification_type=notification_type, message_id=message_id)
                            session.add(notification)
                            await session.commit()
                            logger.info(f"[NOTIFY] Уведомление отправлено: DBMessage={message_id}, Employee={employee_id}, Type={notification_type}")
                        except Exception as e:
                            logger.error(f"[NOTIFY] Ошибка отправки: DBMessage={message_id}, Employee={employee_id}, Type={notification_type}: {e}")
                    else:
                        logger.info(f"[NOTIFY] Сотрудник неактивен или не найден: Employee={employee_id}")
                else:
                    logger.info(f"[NOTIFY] Сообщение уже отвечено или не найдено: DBMessage={message_id}")
        except asyncio.CancelledError:
            logger.info(f"[NOTIFY] Уведомление отменено: DBMessage={message_id}, Employee={employee_id}, Type={notification_type}")
        finally:
            if message_id in self.scheduled_tasks:
                self.scheduled_tasks[message_id] = [t for t in self.scheduled_tasks[message_id] if not t.done()]
                if not self.scheduled_tasks[message_id]:
                    del self.scheduled_tasks[message_id]
    
    async def cancel_notifications(self, message_id: int):
        logger.info(f"[NOTIFY] Отмена уведомлений: DBMessage={message_id}")
        if message_id in self.scheduled_tasks:
            for task in self.scheduled_tasks[message_id]:
                if not task.done():
                    task.cancel()
        else:
            logger.info(f"[NOTIFY] Нет задач для отмены: DBMessage={message_id}")
    
    async def _get_warning_text(self, delay_minutes, message):
        chat_id = message.chat_id if hasattr(message, 'chat_id') else message.chat.id
        abs_chat_id = abs(chat_id)
        chat_username = getattr(message, 'chat_username', None)
        chat_link = None
        # Логируем содержимое message.chat
        try:
            logger.info(f"[NOTIFY-DEBUG] message.chat: {getattr(message, 'chat', None)}")
        except Exception as e:
            logger.warning(f"[NOTIFY-DEBUG] Не удалось залогировать message.chat: {e}")
        if not chat_username and hasattr(self.bot, 'get_chat'):
            try:
                chat = await self.bot.get_chat(chat_id)
                logger.info(f"[NOTIFY-DEBUG] self.bot.get_chat({chat_id}): {chat}")
                chat_username = getattr(chat, 'username', None)
                if chat_username:
                    logger.info(f"[NOTIFY-DEBUG] Получен username чата: {chat_username}")
                else:
                    logger.info(f"[NOTIFY-DEBUG] Username чата отсутствует")
            except Exception as e:
                logger.warning(f"[NOTIFY-DEBUG] Ошибка при self.bot.get_chat({chat_id}): {e}")
                chat_username = None
        if chat_username:
            chat_link = f"https://t.me/{chat_username}"
            chat_line = f"Чат: <a href='{chat_link}'>Перейти в чат</a>"
        else:
            # ВСЕГДА пробуем получить новую invite_link через API
            try:
                invite_link = await self.bot.export_chat_invite_link(chat_id)
            except Exception as e:
                logger.warning(f"[NOTIFY] Не удалось получить invite-ссылку для чата {chat_id}: {e}")
                invite_link = None
            if invite_link:
                chat_line = f"Чат: <a href='{invite_link}'>Рабочий чат</a>"
            else:
                chat_line = f"Чат: <code>{chat_id}</code> (приватный, ссылка недоступна)"

        # Формируем ссылку на профиль клиента
        client_profile = None
        if getattr(message, 'client_username', None):
            client_profile = f"<a href='https://t.me/{message.client_username}'>@{message.client_username}</a> (ID: {message.client_telegram_id})"
        else:
            client_profile = f"ID клиента: <code>{message.client_telegram_id}</code>"

        return (
            f"⚠️ <b>Вы не ответили на сообщение клиента!</b>\n"
            f"\n"
            f"{chat_line}\n"
            f"{client_profile}\n"
            f"Текст: {message.message_text[:50]}...\n"
            f"\n"
            f"⏱ <b>Время ожидания:</b> {delay_minutes/60} мин."
        )
    
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
        avg_response_time = stats_obj.avg_response_time
        efficiency_percent = stats_obj.efficiency_percent
        response_rate = stats_obj.response_rate
        unique_clients = stats_obj.unique_clients
        exceeded_15_min = stats_obj.exceeded_15_min
        exceeded_30_min = stats_obj.exceeded_30_min
        exceeded_60_min = stats_obj.exceeded_60_min
        deleted_messages = stats_obj.deleted_messages

        # Формируем текст отчета
        text = "📊 <b>Ваша статистика за сегодня:</b>\n\n"
        
        # Основные показатели
        text += f"📨 Всего сообщений: {total_messages}\n"
        text += f"✅ Отвечено: {responded_messages}\n"
        text += f"❌ Пропущено: {missed_messages}\n"
        
        if deleted_messages > 0:
            text += f"🗑 Удалено клиентами: {deleted_messages}\n"
        
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
        
        if efficiency_percent:
            text += f"📈 Эффективность: {round(efficiency_percent, 1)}%\n"
        
        if response_rate:
            text += f"🎯 Процент ответов: {round(response_rate, 1)}%\n"
        
        if unique_clients:
            text += f"👥 Уникальных клиентов: {unique_clients}\n"
        
        # Дополнительная информация
        text += "\n💡 <i>Продолжайте в том же духе!</i>"
        
        try:
            # Получаем информацию о сотруднике
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Employee).where(Employee.id == employee_id)
                )
                employee = result.scalar_one_or_none()
                
                if employee and employee.is_active:
                    await self.bot.send_message(
                        employee.telegram_id,
                        text,
                        parse_mode="HTML"
                    )
                    logger.info(f"Ежедневный отчет отправлен сотруднику {employee_id}")
                else:
                    logger.info(f"Сотрудник {employee_id} не найден или неактивен - отчет не отправлен")
        except Exception as e:
            logger.error(f"Ошибка при отправке ежедневного отчета сотруднику {employee_id}: {e}")
    
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

    async def get_next_9am_moscow_utc(self):
        """Возвращает datetime следующего 9:00 по МСК в UTC"""
        moscow_tz = pytz.timezone('Europe/Moscow')
        moscow_now = datetime.now(moscow_tz)

        # Создаем 9:00 сегодня
        today_9am = moscow_now.replace(hour=9, minute=0, second=0, microsecond=0)

        # Определяем следующее 9:00
        if moscow_now < today_9am:
            next_9am_moscow = today_9am
        else:
            next_9am_moscow = today_9am + timedelta(days=1)

        # Конвертируем в UTC
        next_9am_utc = next_9am_moscow.astimezone(pytz.UTC).replace(tzinfo=None)
        return next_9am_utc