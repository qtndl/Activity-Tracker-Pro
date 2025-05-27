import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeChat, BotCommandScopeDefault, BotCommandScopeAllGroupChats
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from config.config import settings
from database.database import init_db, AsyncSessionLocal
from database.models import Employee, Message as DBMessage, Notification, ChatEmployee
from .analytics import AnalyticsService
from .notifications import NotificationService
from .handlers import register_handlers_and_scheduler

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=settings.bot_token)
dp = Dispatcher()


class MessageTracker:
    def __init__(self):
        self.pending_messages = {}  # {chat_id: {telegram_message_id: (employee_id_who_first_got_it, original_received_at)}}
        self.analytics = AnalyticsService()
        self.notifications = NotificationService(bot)
    
    async def track_message(self, message: Message, employee_id: int):
        """Отслеживание входящего сообщения от клиента.
        Уведомления планируются только для первого активного сообщения от клиента в чате.
        """
        chat_id = message.chat.id
        telegram_message_id = message.message_id # ID сообщения из Telegram
        client_telegram_id = message.from_user.id

        # Сначала сохраняем DBMessage для статистики и для всех сотрудников
        async with AsyncSessionLocal() as session:
            db_message = DBMessage(
                employee_id=employee_id,
                chat_id=chat_id,
                message_id=telegram_message_id, # ID сообщения из Telegram
                client_telegram_id=client_telegram_id,
                client_username=message.from_user.username,
                client_name=message.from_user.full_name,
                message_text=message.text,
                received_at=datetime.utcnow()
            )
            session.add(db_message)
            await session.commit()
            # db_message.id теперь доступен (PK из нашей БД)

            # --- Подробное логирование: ищем активные сессии ---
            earlier_active_messages_stmt = select(DBMessage.id, DBMessage.responded_at, DBMessage.is_deleted, DBMessage.received_at).where(
                and_(
                    DBMessage.chat_id == chat_id,
                    DBMessage.client_telegram_id == client_telegram_id,
                    DBMessage.employee_id == employee_id,
                    DBMessage.responded_at.is_(None),
                    DBMessage.is_deleted == False,
                    DBMessage.id != db_message.id,
                    DBMessage.received_at < db_message.received_at
                )
            )
            earlier_active_result = await session.execute(earlier_active_messages_stmt)
            earlier_msgs = earlier_active_result.all()
            if earlier_msgs:
                logger.info(f"[DEBUG] Для сотрудника {employee_id} и клиента {client_telegram_id} в чате {chat_id} найдены активные DBMessage:")
                for row in earlier_msgs:
                    logger.info(f"  [DEBUG ACTIVE] id={row.id}, responded_at={row.responded_at}, is_deleted={row.is_deleted}, received_at={row.received_at}")
            else:
                logger.info(f"[DEBUG] Нет других активных DBMessage для сотрудника {employee_id} и клиента {client_telegram_id} в чате {chat_id}")

            already_active_session_for_employee = len(earlier_msgs) > 0

            if not already_active_session_for_employee:
                # Это первое сообщение в сессии для этого сотрудника, или предыдущие были отвечены.
                # Планируем уведомления для текущего db_message.id
                logger.info(f"Планируем уведомления для DBMessage.id={db_message.id} (клиент {client_telegram_id}, сотрудник {employee_id}), т.к. нет других активных сессий.")
                await self.notifications.schedule_warnings_for_message(db_message.id, employee_id, chat_id)
            else:
                logger.info(f"НЕ планируем уведомления для DBMessage.id={db_message.id} (клиент {client_telegram_id}, сотрудник {employee_id}), т.к. уже есть активная сессия.")

        # Обновляем pending_messages (этот словарь может понадобиться для быстрой проверки, кто из сотрудников получил сообщение первым, если решим так делать)
        # Ключ: ID сообщения из Telegram. Значение: (employee_id первого сотрудника, время получения в UTC)
        # Эта часть может потребовать пересмотра, если pending_messages используется для других целей.
        # Пока что, если сообщение новое для этого чата/сообщения, записываем.
        if chat_id not in self.pending_messages:
            self.pending_messages[chat_id] = {}
        
        # Если для этого telegram_message_id еще нет записи в pending_messages, 
        # или если мы хотим перезаписывать (например, чтобы отслеживать последнего назначенного сотрудника - но текущая логика не такова),
        # то добавляем/обновляем. 
        # Текущая логика self.pending_messages не очень ясна из предыдущего кода, поэтому оставляю как было, 
        # но с комментарием, что она может быть не нужна или изменена.
        if telegram_message_id not in self.pending_messages[chat_id]:
             self.pending_messages[chat_id][telegram_message_id] = (employee_id, datetime.utcnow()) # Возможно, здесь лучше db_message.received_at
             logger.debug(f"Сообщение Telegram.ID {telegram_message_id} добавлено в pending_messages для чата {chat_id}")
        
    async def mark_as_responded(self, employee_reply_message: Message, responding_employee_id: int):
        """Отметка сообщения как отвеченного.
        Если сотрудник отвечает на ЛЮБОЕ сообщение клиента,
        все активные сообщения от этого клиента в этом чате считаются отвеченными этим сотрудником.
        Время ответа считается от самого раннего неотвеченного сообщения этого клиента в чате."""
        if not employee_reply_message.reply_to_message:
            logger.warning(f"Сообщение от сотрудника {responding_employee_id} не является ответом. Нечего отмечать.")
            return

        chat_id = employee_reply_message.chat.id
        client_telegram_id = employee_reply_message.reply_to_message.from_user.id
        logger.info(f"[DEBUG] Начало mark_as_responded: chat_id={chat_id}, client_telegram_id={client_telegram_id}, responding_employee_id={responding_employee_id}")

        # Получаем ID сотрудника из базы данных
        async with AsyncSessionLocal() as session:
            employee_result = await session.execute(
                select(Employee).where(Employee.telegram_id == responding_employee_id)
            )
            employee = employee_result.scalar_one_or_none()
            
            if not employee:
                logger.error(f"Сотрудник с Telegram ID {responding_employee_id} не найден в базе данных")
                return
            
            logger.info(f"[ASSERT DEBUG] employee.id={employee.id}, employee.telegram_id={employee.telegram_id}, employee.full_name={employee.full_name}")
            assert employee.id != employee.telegram_id, f"BUG: employee.id == telegram_id! {employee.id}"
            
            logger.info(f"[DEBUG] Найден сотрудник: id={employee.id}, telegram_id={employee.telegram_id}, name={employee.full_name}")
            
            # Закрываем сессию: отмечаем все неотвеченные сообщения этого клиента в этом чате для всех сотрудников
            all_db_messages_for_client = await session.execute(
                select(DBMessage).where(
                    and_(
                        DBMessage.chat_id == chat_id,
                        DBMessage.client_telegram_id == client_telegram_id,
                        DBMessage.responded_at.is_(None),
                        DBMessage.is_deleted == False
                    )
                )
            )
            db_messages_to_update = all_db_messages_for_client.scalars().all()
            logger.info(f"[DEBUG] Найдено {len(db_messages_to_update)} неотвеченных сообщений для обновления")
            
            if db_messages_to_update:
                logger.info(f"[SESSION-CLOSE] Найдено {len(db_messages_to_update)} DBMessage для клиента {client_telegram_id} в чате {chat_id} — закрываем сессию.")
                for db_msg in db_messages_to_update:
                    logger.info(f"[SESSION-CLOSE] Закрываем DBMessage.id={db_msg.id}, employee_id={db_msg.employee_id}, message_id={db_msg.message_id}, received_at={db_msg.received_at}")
                    db_msg.responded_at = datetime.utcnow()
                    db_msg.answered_by_employee_id = employee.id  # Используем ID сотрудника из базы данных
                    logger.info(f"[DEBUG] Установлен answered_by_employee_id={employee.id} для сообщения {db_msg.id}")
                    await self.notifications.cancel_notifications(db_msg.id)
                await session.commit()
                logger.info(f"[SESSION-CLOSE] Сессия клиента {client_telegram_id} в чате {chat_id} закрыта для сотрудника {employee.id}.")
            else:
                logger.info(f"[SESSION-CLOSE] Не найдено DBMessage для клиента {client_telegram_id} в чате {chat_id} — возможно, уже отвечено или удалено.")

    async def mark_as_deleted(self, chat_id: int, message_id: int): # message_id здесь это Telegram message_id
        """Отметка сообщения как удаленного"""
        logger.info(f"🗑 Сообщение Telegram.ID={message_id} удалено в чате {chat_id}")
        # Обновляем в БД ВСЕ копии этого сообщения (для всех сотрудников)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(DBMessage).where(
                    and_(
                        DBMessage.chat_id == chat_id,
                        DBMessage.message_id == message_id  # Используем Telegram message_id для поиска всех копий
                    )
                )
            )
            db_message_copies = result.scalars().all()

            if not db_message_copies:
                logger.warning(f"Не найдено DBMessage записей для Telegram.ID={message_id} в чате {chat_id} для пометки как удаленное.")
                return

            deleted_count = 0
            for db_message_copy in db_message_copies:
                if not db_message_copy.is_deleted:  # Если еще не помечено как удаленное
                    db_message_copy.is_deleted = True
                    db_message_copy.deleted_at = datetime.utcnow()

                    # Отменяем уведомления для этого конкретного DBMessage.id
                    await self.notifications.cancel_notifications(db_message_copy.id)
                    deleted_count += 1
                    logger.info(f"✅ Сообщение DBMessage.id={db_message_copy.id} (Telegram.ID={message_id}) помечено как удаленное для сотрудника {db_message_copy.employee_id}")

            if deleted_count > 0:
                await session.commit()
                logger.info(f"✅ Помечено как удаленные {deleted_count} DBMessage записей для Telegram.ID={message_id}.")

        # Удаляем из отслеживаемых pending_messages (если такой ключ там был)
        if chat_id in self.pending_messages and message_id in self.pending_messages[chat_id]:
            del self.pending_messages[chat_id][message_id]
            logger.info(f"🗑 Удалено из pending_messages: Telegram.ID={message_id} в чате {chat_id}")
    
    async def schedule_notifications(self, message_id: int, employee_id: int, chat_id: int):
        """Планирование уведомлений с актуальными настройками из БД"""
        # Используем метод NotificationService который правильно читает настройки из БД
        await self.notifications.schedule_warnings_for_message(message_id, employee_id, chat_id)


# Создаем экземпляр трекера
message_tracker = MessageTracker()


@dp.message(CommandStart())
async def start_command(message: Message):
    """Обработчик команды /start - ТОЛЬКО в личных сообщениях"""
    # Игнорируем команды в группах
    if message.chat.type != "private":
        return
    
    await message.answer(
        "👋 Добро пожаловать в систему мониторинга активности сотрудников!\n\n"
        "Я помогу отслеживать:\n"
        "• ⏱ Время ответа на сообщения\n"
        "• 📊 Количество обработанных клиентов\n"
        "• ⚠️ Пропущенные сообщения\n"
        "• 📈 Статистику работы\n\n"
        "🔐 <b>Для входа в веб-панель:</b>\n"
        f"1. Откройте: http://localhost:{settings.web_port}/login\n"
        f"2. Введите ваш Telegram ID: <code>{message.from_user.id}</code>\n"
        "3. Получите код в этом чате и введите его\n\n"
        "📊 <b>Команды:</b>\n"
        "/stats - ваша статистика\n"
        "/help - подробная справка\n\n"
        "⚠️ <i>В группах я работаю незаметно - только отслеживаю сообщения!</i>",
        parse_mode="HTML"
    )


@dp.message(Command("stats"))
async def stats_command(message: Message):
    """Показать статистику сотрудника - ТОЛЬКО в личных сообщениях"""
    if message.chat.type != "private":
        return
    
    user_telegram_id = message.from_user.id
    logger.info(f"Запрос /stats от пользователя {user_telegram_id}")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Employee).where(Employee.telegram_id == user_telegram_id)
        )
        employee = result.scalar_one_or_none()
        
        if not employee:
            logger.warning(f"Пользователь {user_telegram_id} не найден в системе.")
            await message.answer("❌ Вы не зарегистрированы в системе")
            return
        
        logger.info(f"Сотрудник найден: {employee.id} - {employee.full_name}")
        
        from web.services.statistics_service import StatisticsService
        stats_service = StatisticsService(session)
        
        # --- Логирование перед вызовом get_employee_stats ---
        period_start_debug, period_end_debug = stats_service._get_period_dates("today")
        logger.info(f"[DEBUG /stats] Для employee_id={employee.id}, период: {period_start_debug} - {period_end_debug}")
        messages_for_stats_debug = await stats_service._get_messages_for_period(employee.id, period_start_debug, period_end_debug)
        logger.info(f"[DEBUG /stats] Сообщения, полученные _get_messages_for_period для employee_id={employee.id} ({len(messages_for_stats_debug)} шт.):")
        for i, msg_debug in enumerate(messages_for_stats_debug):
            logger.info(f"  [DEBUG MSG {i+1}] id={msg_debug.id}, text='{msg_debug.message_text[:20]}...', received_at={msg_debug.received_at}, responded_at={msg_debug.responded_at}, answered_by={msg_debug.answered_by_employee_id}, deleted={msg_debug.is_deleted}")
        # --- Конец логирования перед вызовом ---
        
        stats: EmployeeStats = await stats_service.get_employee_stats(employee.id, period="today")
        
        logger.info(f"[DEBUG /stats] Получена статистика для employee_id={employee.id}:")
        logger.info(f"  Total: {stats.total_messages}, Responded (by this emp): {stats.responded_messages}, Missed (by this emp): {stats.missed_messages}, Deleted: {stats.deleted_messages}")
        logger.info(f"  Unique Clients: {stats.unique_clients}, Avg Resp Time: {stats.avg_response_time}, Efficiency: {stats.efficiency_percent}")
        logger.info(f"  Exceeded 15/30/60: {stats.exceeded_15_min}/{stats.exceeded_30_min}/{stats.exceeded_60_min}")
        
        if stats:
            # Форматируем дату как в веб-интерфейсе
            today = datetime.now().strftime("%d.%m.%Y")
            
            text = f"📊 <b>Детализированная статистика</b>\n\n"
            text += f"📅 <b>Период:</b> {today}\n"
            text += f"👤 <b>Сотрудник:</b> {employee.full_name}\n\n"
            
            # Основные метрики
            text += f"📨 <b>Всего сообщений:</b> {stats.total_messages}\n"
            text += f"✅ <b>Отвечено:</b> {stats.responded_messages}\n"
            text += f"❌ <b>Пропущено:</b> {stats.missed_messages}\n"
            text += f"👥 <b>Уникальных клиентов:</b> {stats.unique_clients}\n"
            # Проверка на None для avg_response_time
            avg_response_time_text = f"{stats.avg_response_time:.1f}м" if stats.avg_response_time is not None else "0.0м"
            text += f"⏱ <b>Среднее время ответа:</b> {avg_response_time_text}\n\n"
            
            # Предупреждения по времени
            text += f"⚠️ <b>Ответов > 15м:</b> {stats.exceeded_15_min}\n"
            text += f"⚠️ <b>Ответов > 30м:</b> {stats.exceeded_30_min}\n"
            text += f"⚠️ <b>Ответов > 60м:</b> {stats.exceeded_60_min}\n\n"
            
            # Эффективность
            # Проверка на None для efficiency_percent (хотя он float и должен быть 0.0 если нет данных)
            efficiency_percent_text = f"{stats.efficiency_percent:.1f}%" if stats.efficiency_percent is not None else "0.0%"
            text += f"📈 <b>Эффективность:</b> {efficiency_percent_text}\n"
            
            # Добавляем информацию об удаленных сообщениях если они есть
            if stats.deleted_messages > 0:
                text += f"\n🗑 <b>Удалено клиентами:</b> {stats.deleted_messages}\n"
                text += f"💡 <i>Удаленные клиентами сообщения не считаются пропущенными</i>"
        else:
            text = "📊 Статистика за сегодня пока отсутствует"
        
        # Если админ — добавляем общую статистику по всем сотрудникам
        if employee.is_admin:
            summary = await stats_service.get_dashboard_overview(user_id=employee.id, is_admin=True, period='today')
            
            text += "\n\n📊 <b>Общая статистика по всем сотрудникам:</b>\n\n"
            text += f"📨 <b>Всего сообщений:</b> {summary['total_messages_today']}\n"
            text += f"✅ <b>Отвечено:</b> {summary['responded_today']}\n"
            text += f"❌ <b>Пропущено:</b> {summary['missed_today']}\n"
            text += f"👥 <b>Уникальных клиентов:</b> {summary['unique_clients_today']}\n"
            # Проверка на None для avg_response_time в общей статистике
            summary_avg_response_time_text = f"{summary['avg_response_time']:.1f}м" if summary.get('avg_response_time') is not None else "0.0м"
            text += f"⏱ <b>Среднее время ответа:</b> {summary_avg_response_time_text}\n"
            summary_efficiency_text = f"{summary['efficiency_today']:.1f}%" if summary.get('efficiency_today') is not None else "0.0%"
            text += f"📈 <b>Эффективность:</b> {summary_efficiency_text}"
        
        await message.answer(text, parse_mode="HTML")


@dp.message(F.chat.type.in_(['group', 'supergroup']))
async def handle_group_message(message: Message):
    """Обработчик сообщений в группах"""
    
    # Игнорируем системные сообщения
    if (message.new_chat_members or 
        message.left_chat_member or 
        message.new_chat_title or 
        message.new_chat_photo or 
        message.delete_chat_photo or 
        message.group_chat_created or 
        message.supergroup_chat_created or 
        message.channel_chat_created or 
        message.migrate_to_chat_id or 
        message.migrate_from_chat_id or 
        message.pinned_message or
        not message.text):  # Игнорируем сообщения без текста (стикеры, фото и т.д.)
        logger.info(f"🚫 Игнорируем системное/нетекстовое сообщение в чате {message.chat.id}")
        return
    
    logger.info(f"📩 Получено сообщение от {message.from_user.full_name} (ID: {message.from_user.id}) в чате {message.chat.id}: '{message.text[:50]}...' ")
    async with AsyncSessionLocal() as session:
        # Получаем всех активных сотрудников и админов из БД
        active_employees_result = await session.execute(
            select(Employee).where(Employee.is_active == True)
        )
        all_active_employees = active_employees_result.scalars().all()
        sender_is_employee = any(emp.telegram_id == message.from_user.id for emp in all_active_employees)
        if sender_is_employee:
            # Если это reply на сообщение клиента — засчитываем как ответ
            if message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id != message.from_user.id:
                logger.info(f"✅ Сотрудник/админ {message.from_user.full_name} (ID: {message.from_user.id}) отвечает на сообщение клиента — засчитываем как ответ.")
                await message_tracker.mark_as_responded(message, message.from_user.id)
            else:
                logger.info(f"🗣️ Сообщение от сотрудника/админа {message.from_user.full_name} (ID: {message.from_user.id}) — не трекаем как клиента.")
            return
        # Проверяем, кто реально состоит в чате
        real_group_members = []
        for employee_obj in all_active_employees:
            try:
                member = await bot.get_chat_member(message.chat.id, employee_obj.telegram_id)
                if member.status not in ("left", "kicked"):
                    real_group_members.append(employee_obj)
                else:
                    logger.info(f"Сотрудник {employee_obj.full_name} (id={employee_obj.id}) не состоит в группе, не уведомляем.")
            except Exception as e:
                logger.warning(f"Не удалось проверить членство сотрудника {employee_obj.full_name} (id={employee_obj.id}) в группе: {e}")
        if not real_group_members:
            logger.warning(f"Нет сотрудников/админов, реально состоящих в группе {message.chat.id} для уведомления.")
            return
        for employee_obj in real_group_members:
            await message_tracker.track_message(message, employee_obj.id)
            logger.info(f"📊 Трекаем сообщение для сотрудника: {employee_obj.full_name} (ID: {employee_obj.id}) [реально в группе]")


async def setup_bot_commands():
    """Настройка команд бота"""
    # Команды для личных чатов
    private_commands = [
        BotCommand(command="start", description="🚀 Начало работы"),
        BotCommand(command="help", description="❓ Помощь и инструкции"),
        BotCommand(command="stats", description="📊 Моя статистика"),
    ]
    
    # Устанавливаем команды для личных чатов
    await bot.set_my_commands(commands=private_commands, scope=BotCommandScopeDefault())
    
    # Очищаем команды для групп (пустой список)
    await bot.set_my_commands(commands=[], scope=BotCommandScopeAllGroupChats())
    
    logger.info("✅ Меню команд настроено: личные чаты - есть команды, группы - без меню")


async def main():
    """Основная функция запуска бота"""
    # Инициализация БД
    await init_db()
    
    # Регистрация обработчиков
    await register_handlers_and_scheduler(dp, message_tracker)
    
    # Настройка команд бота
    await setup_bot_commands()
    
    # Запуск бота
    logger.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main()) 