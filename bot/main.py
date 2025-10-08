import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeChat, BotCommandScopeDefault, BotCommandScopeAllGroupChats, CallbackQuery
from sqlalchemy import select, and_, func, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from config.config import settings
from database.database import init_db, AsyncSessionLocal
from database.models import Message as DBMessage, DeferredMessageSimple, Employee
from .settings_manager import settings_manager
from .analytics import AnalyticsService
from .notifications import NotificationService
from .handlers import register_handlers_and_scheduler
from web.services.statistics_service import EmployeeStats

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
            deferred_messages = await session.execute(
                select(DeferredMessageSimple).where(
                        and_(
                            DBMessage.chat_id == chat_id,
                            DBMessage.client_telegram_id == client_telegram_id,
                            DBMessage.is_deferred == True,
                            DBMessage.is_deleted == False
                        )
                    )
                )
            deferred_msgs = deferred_messages.scalars().all()
            if deferred_msgs:
                for def_msg in deferred_msgs:
                    def_msg.is_active = False
                    def_msg.original_message.is_deferred = False
            await session.commit()
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
                now = datetime.utcnow()
                for db_msg in db_messages_to_update:
                    logger.info(f"[SESSION-CLOSE] Закрываем DBMessage.id={db_msg.id}, employee_id={db_msg.employee_id}, message_id={db_msg.message_id}, received_at={db_msg.received_at}")
                    db_msg.responded_at = now
                    db_msg.answered_by_employee_id = employee.id  # Используем ID сотрудника из базы данных
                    # Вычисляем время ответа
                    if now >= db_msg.received_at:
                        time_diff = now - db_msg.received_at
                        # db_msg.response_time_minutes = time_diff.total_seconds() / 60
                    else:
                        db_msg.received_at = now
                        time_diff = now - now
                    db_msg.response_time_minutes = time_diff.total_seconds() / 60
                    logger.info(f"[DEBUG] Установлен answered_by_employee_id={employee.id} и response_time_minutes={db_msg.response_time_minutes:.1f} для сообщения {db_msg.id}")
                    await self.notifications.cancel_notifications(db_msg.id)
                await session.commit()
                logger.info(f"[SESSION-CLOSE] Сессия клиента {client_telegram_id} в чате {chat_id} закрыта для сотрудника {employee.id}.")
            else:
                logger.info(f"[SESSION-CLOSE] Не найдено DBMessage для клиента {client_telegram_id} в чате {chat_id} — возможно, уже отвечено или удалено.")

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
        f"1. Откройте: http://{settings.web_host}:{settings.web_port}/login\n"
        f"2. Введите ваш Telegram ID: <code>{message.from_user.id}</code>\n"
        "3. Получите код в этом чате и введите его\n\n"
        "📊 <b>Команды:</b>\n"
        "/stats - ваша статистика\n"
        "/help - подробная справка\n\n"
        "⚠️ <i>В группах я работаю незаметно - только отслеживаю сообщения!</i>",
        parse_mode="HTML"
    )

@dp.message(Command("help"))
async def help_command(message: Message):
    """Помощь по командам - ТОЛЬКО в личных сообщениях"""
    # Игнорируем команды в группах
    if message.chat.type != "private":
        return

    # Проверяем является ли пользователь админом
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Employee).where(Employee.telegram_id == message.from_user.id)
        )
        employee = result.scalar_one_or_none()

        is_admin = employee and employee.is_admin if employee else False

    help_text = """
🤖 <b>Доступные команды:</b>

/start - Начало работы и вход в веб-панель
/stats - Показать вашу статистику за сегодня
/help - Это сообщение

<b>Как работает бот:</b>
• Бот автоматически отслеживает сообщения в группах
• Отправляет уведомления при долгом отсутствии ответа
• Собирает статистику по времени ответов
• Формирует отчеты для анализа работы
• Удаленные клиентами сообщения не считаются пропущенными

<b>Веб-панель:</b>
Используйте /start для получения ссылки на вход

⚠️ <i>Все команды работают только в личных сообщениях!</i>
    """

    # Добавляем админские команды
    if is_admin:
        help_text += """
<b>👑 Команды администратора:</b>
/admin_stats - Общая статистика по всем сотрудникам
/mark_deleted - Пометить сообщение как удаленное
    """

    await message.answer(help_text, parse_mode="HTML")

@dp.message(Command("report_weekly"))
async def weekly_report_command(message: Message):
    """Недельный отчет - ТОЛЬКО в личных сообщениях"""
    delays_data = await settings_manager._get_settings()
    delays = [
        delays_data['notification_delay_1'],
        delays_data['notification_delay_2'],
        delays_data['notification_delay_3']
    ]
    
    # Игнорируем команды в группах
    if message.chat.type != "private":
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Employee).where(Employee.telegram_id == message.from_user.id)
        )
        employee = result.scalar_one_or_none()

        if not employee:
            await message.answer("❌ Вы не зарегистрированы в системе")
            return

        stats = await message_tracker.analytics.get_employee_stats(employee.id, 'weekly')

        if stats:
            text = f"📊 <b>Ваша статистика за неделю:</b>\n\n"
            text += f"📨 Всего сообщений: {stats['total_messages']}\n"
            text += f"✅ Отвечено: {stats['responded_messages']}\n"
            text += f"❌ Пропущено: {stats['missed_messages']}\n"
            if stats['deferred_messages'] > 0:
                    text += f"🕓 Отложено: {stats['deferred_messages']}\n"

            if stats['responded_messages'] > 0:
                text += f"\n⏱ Среднее время ответа: {stats['avg_response_time']:.1f} мин\n"
                text += f"\n⚠️ Превышений времени ответа:\n"
                text += f"  • Более {delays[0]} мин: {stats['exceeded_15_min']}\n"
                text += f"  • Более {delays[1]} мин: {stats['exceeded_30_min']}\n"
                text += f"  • Более {delays[2]} мин: {stats['exceeded_60_min']}"

            # Расчет эффективности
            if stats['total_messages'] > 0:
                efficiency = (stats['responded_messages'] / stats['total_messages']) * 100
                text += f"\n\n📈 Эффективность: {efficiency:.1f}%"
        else:
            text = "📊 Статистика за неделю пока отсутствует"

        await message.answer(text, parse_mode="HTML")

@dp.message(Command("report_monthly"))
async def monthly_report_command(message: Message):
    """Месячный отчет - ТОЛЬКО в личных сообщениях"""
    delays_data = await settings_manager._get_settings()
    delays = [
        delays_data['notification_delay_1'],
        delays_data['notification_delay_2'],
        delays_data['notification_delay_3']
    ]

    # Игнорируем команды в группах
    if message.chat.type != "private":
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Employee).where(Employee.telegram_id == message.from_user.id)
        )
        employee = result.scalar_one_or_none()

        if not employee:
            await message.answer("❌ Вы не зарегистрированы в системе")
            return

        stats = await message_tracker.analytics.get_employee_stats(employee.id, 'monthly')

        if stats:
            text = f"📊 <b>Ваша статистика за месяц:</b>\n\n"
            text += f"📨 Всего сообщений: {stats['total_messages']}\n"
            text += f"✅ Отвечено: {stats['responded_messages']}\n"
            text += f"❌ Пропущено: {stats['missed_messages']}\n"
            if stats['deferred_messages'] > 0:
                    text += f"🕓 Отложено: {stats['deferred_messages']}\n"

            if stats['responded_messages'] > 0:
                text += f"\n⏱ Среднее время ответа: {stats['avg_response_time']:.1f} мин\n"
                text += f"\n⚠️ Превышений времени ответа:\n"
                text += f"  • Более {delays[0]} мин: {stats['exceeded_15_min']}\n"
                text += f"  • Более {delays[1]} мин: {stats['exceeded_30_min']}\n"
                text += f"  • Более {delays[2]} мин: {stats['exceeded_60_min']}"

            # Расчет эффективности и средних показателей
            if stats['total_messages'] > 0:
                efficiency = (stats['responded_messages'] / stats['total_messages']) * 100
                avg_daily = stats['total_messages'] / 30  # Примерно

                text += f"\n\n📈 Эффективность: {efficiency:.1f}%"
                text += f"\n📅 В среднем в день: {avg_daily:.1f} сообщений"
        else:
            text = "📊 Статистика за месяц пока отсутствует"

        await message.answer(text, parse_mode="HTML")

@dp.message(Command("admin_stats"))
async def admin_stats_command(message: Message):
    """Статистика для администратора - ТОЛЬКО в личных сообщениях"""
    # Игнорируем команды в группах
    if message.chat.type != "private":
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Employee).where(
                Employee.telegram_id == message.from_user.id,
                Employee.is_admin == True
            )
        )
        admin = result.scalar_one_or_none()

        if not admin:
            await message.answer("❌ У вас нет прав администратора")
            return

        # Получаем статистику всех сотрудников
        employees_result = await session.execute(
            select(Employee).where(Employee.is_active == True)
        )
        employees = employees_result.scalars().all()

        text = "👥 <b>Статистика по всем сотрудникам за сегодня:</b>\n\n"

        total_messages = 0
        total_responded = 0
        total_missed = 0
        total_deleted = 0
        total_deferred = 0

        for employee in employees:
            stats = await message_tracker.analytics.get_employee_stats(employee.id, 'daily')
            if stats:
                text += f"👤 <b>{employee.full_name}</b>\n"
                text += f"  📨 Сообщений: {stats['total_messages']}\n"
                text += f"  ✅ Отвечено: {stats['responded_messages']}\n"
                text += f"  ❌ Пропущено: {stats['missed_messages']}\n"
                if stats['deferred_messages'] > 0:
                    text += f"  🕓 Отложено: {stats['deferred_messages']}\n"

                if stats.get('deleted_messages', 0) > 0:
                    text += f"  🗑 Удалено: {stats['deleted_messages']}\n"

                if stats['responded_messages'] > 0:
                    text += f"  ⏱ Среднее время: {stats['avg_response_time']:.1f} мин\n"

                text += "\n"

                total_messages += stats['total_messages']
                total_responded += stats['responded_messages']
                total_missed += stats['missed_messages']
                total_deleted += stats.get('deleted_messages', 0)
                total_deferred += stats.get('deferred_messages', 0)

        text += f"\n📊 <b>Итого:</b>\n"
        text += f"📨 Всего сообщений: {total_messages}\n"
        text += f"✅ Отвечено: {total_responded}\n"
        text += f"❌ Пропущено: {total_missed}\n"

        if total_deferred > 0:
            text += f"🕓 Отложено: {total_deferred}\n"

        if total_deleted > 0:
            text += f"🗑 Удалено: {total_deleted}\n"

        if total_messages > 0:
            overall_efficiency = ((total_responded + total_deleted) / total_messages) * 100
            text += f"📈 Общая эффективность: {overall_efficiency:.1f}%"

        await message.answer(text, parse_mode="HTML")

@dp.message(Command("mark_deleted"))
async def mark_deleted_command(message: Message):
    """Полное удаление сообщения (только для админов) - ТОЛЬКО в личных сообщениях"""
    if message.chat.type != "private":
        return
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Employee).where(
                Employee.telegram_id == message.from_user.id,
                Employee.is_admin == True
            )
        )
        admin = result.scalar_one_or_none()
        if not admin:
            await message.answer("❌ У вас нет прав администратора")
            return
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        if len(args) < 2:
            await message.answer(
                "ℹ️ <b>Использование:</b>\n"
                "<code>/mark_deleted CHAT_ID MESSAGE_ID</code>\n\n"
                "<b>Пример:</b>\n"
                "<code>/mark_deleted -1001234567890 123</code>\n\n"
                "Эта команда полностью удалит сообщение из базы для всех сотрудников.",
                parse_mode="HTML"
            )
            return
        try:
            chat_id = int(args[0])
            msg_id = int(args[1])
        except ValueError:
            await message.answer("❌ Неправильный формат. Chat ID и Message ID должны быть числами.")
            return
        # Полное удаление всех копий сообщения
        result = await session.execute(
            select(DBMessage).where(
                DBMessage.chat_id == chat_id,
                DBMessage.message_id == msg_id
            )
        )
        db_messages = result.scalars().all()
        if not db_messages:
            await message.answer("❌ Сообщение не найдено в базе.")
            return
        for db_msg in db_messages:
            await session.delete(db_msg)
        await session.commit()
        await message.answer(
            f"✅ Сообщение {msg_id} в чате {chat_id} полностью удалено из базы.\n\n"
            "Оно больше не будет учитываться нигде в статистике.",
            parse_mode="HTML"
        )

@dp.message(Command("stats"))
async def stats_command(message: Message):
    """Показать статистику сотрудника - ТОЛЬКО в личных сообщениях"""
    if message.chat.type != "private":
        return
    
    user_telegram_id = message.from_user.id
    logger.info(f"Запрос /stats от пользователя {user_telegram_id}")

    delays_data = await settings_manager._get_settings()
    delays = [
        delays_data['notification_delay_1'],
        delays_data['notification_delay_2'],
        delays_data['notification_delay_3']
    ]

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
        messages_for_stats_debug = await stats_service._get_messages_for_period(employee.id, period_start_debug, period_end_debug)
        logger.info(f"[DEBUG /stats] Сообщения, полученные _get_messages_for_period для employee_id={employee.id} ({len(messages_for_stats_debug)} шт.):")
        for i, msg_debug in enumerate(messages_for_stats_debug):
            logger.info(f"  [DEBUG MSG {i+1}] id={msg_debug.id}, text='{msg_debug.message_text[:20]}...', received_at={msg_debug.received_at}, responded_at={msg_debug.responded_at}, answered_by={msg_debug.answered_by_employee_id}, deleted={msg_debug.is_deleted}")
        # --- Конец логирования перед вызовом ---
        stats: EmployeeStats = await stats_service.get_employee_stats(employee.id, period="today")
        # Получаем количество новых отложенных сообщений
        deferred_simple_count = await stats_service.get_deferred_simple_count(employee.id, period="today")
        
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
            # Новые отложенные сообщения
            if deferred_simple_count > 0:
                text += f"🕓 <b>Отложено:</b> {deferred_simple_count}\n"
            text += f"👥 <b>Уникальных клиентов:</b> {stats.unique_clients}\n"
            # Проверка на None для avg_response_time
            avg_response_time_text = f"{stats.avg_response_time:.1f}м" if stats.avg_response_time is not None else "0.0м"
            text += f"⏱ <b>Среднее время ответа:</b> {avg_response_time_text}\n\n"
            
            # Предупреждения по времени
            text += f"⚠️ <b>Ответов > {delays[0]}м:</b> {stats.exceeded_15_min}\n"
            text += f"⚠️ <b>Ответов > {delays[1]}м:</b> {stats.exceeded_30_min}\n"
            text += f"⚠️ <b>Ответов > {delays[2]}м:</b> {stats.exceeded_60_min}\n\n"
            
            # Эффективность
            # Проверка на None для efficiency_percent (хотя он float и должен быть 0.0 если нет данных)
            efficiency_percent_text = f"{stats.efficiency_percent:.1f}%" if stats.efficiency_percent is not None else "0.0%"
            text += f"📈 <b>Эффективность:</b> {efficiency_percent_text}\n"
        else:
            text = "📊 Статистика за сегодня пока отсутствует"
        
        # Если админ — добавляем общую статистику по всем сотрудникам
        if employee.is_admin:
            summary = await stats_service.get_dashboard_overview(user_id=employee.id, is_admin=True, period='today')
            try:
                deferred_msgs = summary['deferred_messages']
            except:
                deferred_msgs = None
            
            text += "\n\n📊 <b>Общая статистика по всем сотрудникам:</b>\n\n"
            text += f"📨 <b>Всего сообщений:</b> {summary['total_messages_today']}\n"
            text += f"✅ <b>Отвечено:</b> {summary['responded_today']}\n"
            text += f"❌ <b>Пропущено:</b> {summary['missed_today']}\n"
            if deferred_msgs:
                text += f"🕓 <b>Отложено:</b> {deferred_msgs}\n"
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


@dp.message(F.chat.type == 'private')
async def handle_private_message(message: Message):
    logger.info(f"[FORWARD-DEBUG] message_id={message.message_id}, chat_id={message.chat.id}, text={repr(message.text)}")
    logger.info(f"[FORWARD-DEBUG] forward_from_chat={getattr(message, 'forward_from_chat', None)}")
    logger.info(f"[FORWARD-DEBUG] forward_from={getattr(message, 'forward_from', None)}")
    logger.info(f"[FORWARD-DEBUG] forward_sender_name={getattr(message, 'forward_sender_name', None)}")
    logger.info(f"[FORWARD-DEBUG] forward_from_message_id={getattr(message, 'forward_from_message_id', None)}")
    logger.info(f"[FORWARD-DEBUG] forward_date={getattr(message, 'forward_date', None)}")
    # Обработка только пересланных сообщений
    if not (message.forward_from_chat or message.forward_from or message.forward_sender_name):
        print('Не удалось')
        return  # Не пересланное — игнорируем

    # Получаем id сотрудника, который переслал сообщение
    async with AsyncSessionLocal() as session:
        orig_msg_id = None
        emp_result = await session.execute(select(Employee).where(Employee.telegram_id == message.from_user.id))
        employee = emp_result.scalar_one_or_none()
        if not employee:
            logger.warning(f"[FORWARD-DEBUG] Сотрудник с telegram_id={message.from_user.id} не найден в базе!")
            await message.answer("Вы не зарегистрированы как сотрудник. Обратитесь к администратору.")
            return
        logger.info(f"[FORWARD-DEBUG] Сотрудник найден: id={employee.id}, full_name={employee.full_name}")
        # --- Новая логика: если пересылается сообщение, то ищем оригинал в Message и делаем его отвеченным ---
        if message.forward_from and message.forward_from.id:
            # Пытаемся найти все оригинальные сообщения клиента в Message, которые считаются пропущенными и неотвеченными
            missed_deferred_msgs_result = await session.execute(select(DBMessage)
                                            .where(DBMessage.client_telegram_id == message.forward_from.id,
                                                   DBMessage.responded_at.is_(None),
                                                   DBMessage.is_deferred == False,
                                                   DBMessage.is_deleted == False)
                                                            )
            missed_deferred_msgs = missed_deferred_msgs_result.scalars().all()
            if not missed_deferred_msgs:
                await message.answer("Нет пропущенных сообщений от клиента. Посмотрите на статистику.")
                return
            orig_result = await session.execute(
                select(DBMessage)
                .where(
                    DBMessage.client_telegram_id == message.forward_from.id,
                    # DBMessage.is_missed == True,
                    DBMessage.responded_at.is_(None),
                    DBMessage.is_deleted == False
                )
                .order_by(DBMessage.received_at)
            )
        elif message.forward_sender_name:
            missed_deferred_msgs_result = await session.execute(select(DBMessage)
                                            .where(DBMessage.client_name == message.forward_sender_name,
                                                   DBMessage.responded_at.is_(None),
                                                   DBMessage.is_deferred == False,
                                                   DBMessage.is_deleted == False)
                                                            )
            missed_deferred_msgs = missed_deferred_msgs_result.scalars().all()
            if not missed_deferred_msgs:
                await message.answer("Нет пропущенных сообщений от клиента. Посмотрите на статистику.")
                return
            orig_result = await session.execute(
                select(DBMessage)
                .where(
                    DBMessage.client_name == message.forward_sender_name,
                    # DBMessage.is_missed == True,
                    DBMessage.responded_at.is_(None),
                    DBMessage.is_deleted == False
                )
                .order_by(DBMessage.received_at)
            )
        else:
            await message.answer("Настройки аккаунта у пользователя на позволяют найти пересылаемое сообщение в чате")
        orig_msgs = orig_result.scalars().all()
        if orig_msgs:
            emp_msgs_list = [[], []]
            for orig_msg in orig_msgs:
                if orig_msg.employee_id==employee.id:
                    emp_msgs_list[0].append(orig_msg)
                else:
                    emp_msgs_list[1].append(orig_msg)
            now = datetime.utcnow()
            for i, emp_msgs in enumerate(emp_msgs_list):
                for ii, emp_msg in enumerate(emp_msgs):
                    if emp_msg.is_deferred:
                        continue
                    if i == 0 and ii == 0:
                        emp_msg.is_deferred = True
                        orig_msg_id = emp_msg.id
                        def_msg_text = emp_msg.message_text
                    if emp_msg.received_at > now:
                        emp_msg.received_at = now
                    emp_msg.responded_at = now
                    time_diff = now - emp_msg.received_at
                    emp_msg.response_time_minutes = time_diff.total_seconds() / 60
                    emp_msg.answered_by_employee_id = employee.id

            await session.commit()
            # --- Конец новой логики ---
        # Добавляем пересланное сообщение в новую таблицу DeferredMessageSimple
        if orig_msg_id is None:
            await message.answer("Не удалось добавить сообщение в отложенные")
            return
        new_deferred = DeferredMessageSimple(
            from_user_id=employee.id,  # сохраняем id сотрудника, а не telegram_id клиента
            from_username=message.forward_sender_name if message.forward_sender_name else None,
            text=def_msg_text,
            date=message.forward_date if message.forward_date else datetime.utcnow(),
            is_active=True,
            created_at=datetime.utcnow(),
            # Новые поля:
            client_telegram_id=message.forward_from.id if message.forward_from and hasattr(message.forward_from, 'id') else None,
            employee_id=employee.id,
            chat_id=message.forward_from_chat.id if message.forward_from_chat and hasattr(message.forward_from_chat, 'id') else None,
            original_message_id=orig_msg_id
        )
        session.add(new_deferred)
        await session.commit()
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Убрать из отложенных", callback_data=f"undefer_simple:{new_deferred.id}"),
            InlineKeyboardButton(text="Удалить", callback_data=f"delete_s:{new_deferred.id}")
        ]])
        await message.answer("Сообщение добавлено в отложенные (новая таблица).", reply_markup=kb)

@dp.callback_query(F.data.startswith("undefer_simple:"))
async def undefer_simple_callback(call: CallbackQuery):
    _, deferred_id = call.data.split(":")
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DeferredMessageSimple).where(DeferredMessageSimple.id == int(deferred_id)))
        deferred = result.scalar_one_or_none()
        if not deferred:
            await call.answer("Сообщение не найдено или уже отвечено", show_alert=True)
            return
        deferred.is_active = False
        # await session.commit()

        if deferred.original_message:
            db_msg = deferred.original_message

            if db_msg:
                now = datetime.utcnow()
                db_msg.is_deferred = False
                db_msg.received_at = now
                db_msg.responded_at = None
                db_msg.response_time_minutes = None
                db_msg.answered_by_employee_id = None
                await session.commit()
                print('Не Фоллбэк')
                await call.answer("Сообщение убрано из отложенных.", show_alert=True)
                await call.message.edit_reply_markup(reply_markup=None)
            else:
                await call.message.answer("Что-то пошло не так", show_alert=True)
        else:
            # Фоллбек: можно по client_name взять последнее неотвеченное
            if deferred.from_username:
                msg_res = await session.execute(
                    select(DBMessage)
                    .where(
                        DBMessage.client_name == deferred.from_username,
                        DBMessage.is_deferred == True
                    )
                    .order_by(DBMessage.received_at.desc())
                    .limit(1)
                )
                db_msg = msg_res.scalar_one_or_none()
                if db_msg:
                    now = datetime.utcnow()
                    db_msg.is_deferred = False
                    db_msg.received_at = now
                    db_msg.responded_at = None
                    db_msg.response_time_minutes = None
                    db_msg.answered_by_employee_id = None
                    await session.commit()
                    print('Фоллбэк')
                    await call.answer("Сообщение убрано из отложенных. (Fallback)", show_alert=True)
                    await call.message.edit_reply_markup(reply_markup=None)
                else:
                    await call.message.answer("Что-то пошло не так", show_alert=True)

@dp.callback_query(F.data.startswith("delete_s:"))
async def delete_simple_callback(call: CallbackQuery):
    another_emp_msg = None
    _, deferred_id = call.data.split(":")
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DeferredMessageSimple).where(DeferredMessageSimple.id == int(deferred_id)))
        deferred = result.scalar_one_or_none()
        if not deferred:
            await call.answer("Сообщение не найдено в базе.", show_alert=True)
            return
        if deferred.original_message:
            db_msg = deferred.original_message
            if db_msg:
                another_emp_msg = int(db_msg.message_id)
                result = await session.execute(select(Employee).where(Employee.is_admin == True))
                admins = result.scalars().all()
                for admin in admins:
                    admin_id = int(admin.telegram_id)
                    await bot.send_message(admin_id, f'Сотрудник @{admin.telegram_username} ({admin.full_name}) удалил сообщение из базы данных:\n'
                                                     f'<blockquote>{db_msg.message_text}</blockquote>\n'
                                                     f'От клиента: @{db_msg.client_username} ({db_msg.client_name})',
                                                    parse_mode='HTML')
                await session.execute(text("DELETE FROM deferred_messages_simple WHERE original_message_id = :message_id"),
                    {"message_id": db_msg.id}
                )
                await session.execute(
                    text("DELETE FROM notifications WHERE message_id = :message_id"),
                    {"message_id": db_msg.id}
                )
                await session.execute(
                    text("DELETE FROM messages WHERE message_id = :message_id"),
                    {"message_id": db_msg.id}
                )
                await session.commit()
                results = await session.execute(select(DBMessage).where(DBMessage.message_id==another_emp_msg))
                anthr_emp_msgs = results.scalars().all()
                if anthr_emp_msgs:
                    for anthr_msg in anthr_emp_msgs:
                        await session.execute(text("DELETE FROM deferred_messages_simple WHERE original_message_id = :message_id"),
                    {"message_id": anthr_msg.message_id}
                        )
                        await session.execute(
                            text("DELETE FROM notifications WHERE message_id = :message_id"),
                            {"message_id": anthr_msg.message_id}
                        )
                        await session.execute(
                            text("DELETE FROM messages WHERE message_id = :message_id"),
                            {"message_id": anthr_msg.message_id}
                        )
                    await session.commit()
                await call.answer("Сообщение удалено из базы.\n"
                                  "Оно больше не будет учитываться нигде в статистике.", show_alert=True)
                await call.message.edit_reply_markup(reply_markup=None)
            else:
                await call.answer("Сообщение не найдено в базе.", show_alert=True)



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
    
    # Настройка команд бота
    await setup_bot_commands()

    # Регистрация обработчиков
    await register_handlers_and_scheduler(dp, message_tracker)

    await settings_manager.get_notification_delays()
    
    # Запуск бота
    logger.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())