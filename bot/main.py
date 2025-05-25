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
from database.models import Employee, Message as DBMessage, Notification
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

            # Проверяем, нужно ли планировать уведомления для ЭТОГО сотрудника
            # (может быть уже есть активная сессия с этим клиентом, и уведомления по ней уже тикают)
            
            # Ищем ДРУГИЕ активные (неотвеченные, не удаленные) DBMessage от этого клиента 
            # в этом чате, назначенные этому же сотруднику, которые были получены РАНЬШЕ текущего.
            # Исключаем текущее db_message.id, если оно уже есть (хотя на этом этапе еще не должно быть в scheduled_tasks)
            earlier_active_messages_stmt = select(DBMessage.id).where(
                and_(
                    DBMessage.chat_id == chat_id,
                    DBMessage.client_telegram_id == client_telegram_id,
                    DBMessage.employee_id == employee_id, # Для этого конкретного сотрудника
                    DBMessage.responded_at.is_(None),
                    DBMessage.is_deleted == False,
                    DBMessage.id != db_message.id, # Исключаем текущее обрабатываемое сообщение
                    DBMessage.received_at < db_message.received_at # Только те, что получены раньше
                )
            ).limit(1) # Нам достаточно одного, чтобы понять, что сессия уже активна
            
            earlier_active_result = await session.execute(earlier_active_messages_stmt)
            already_active_session_for_employee = earlier_active_result.scalar_one_or_none() is not None

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
        Если сотрудник отвечает на одно из сообщений клиента,
        все активные сообщения от этого клиента в этом чате считаются отвеченными этим сотрудником.
        Время ответа считается от самого раннего неотвеченного сообщения этого клиента в чате."""
        if not employee_reply_message.reply_to_message:
            logger.warning(f"Сообщение от сотрудника {responding_employee_id} не является ответом. Нечего отмечать.")
            return

        chat_id = employee_reply_message.chat.id
        # ID конкретного сообщения клиента, на которое ответил сотрудник
        replied_to_client_message_telegram_id = employee_reply_message.reply_to_message.message_id
        # ID самого клиента
        client_telegram_id = employee_reply_message.reply_to_message.from_user.id

        logger.info(f"🔄 Сотрудник ID {responding_employee_id} ответил на сообщение клиента ID {client_telegram_id} (Telegram ID сообщения клиента: {replied_to_client_message_telegram_id}) в чате {chat_id}.")

        calculated_response_time = None
        time_response_anchor_message_id = None # ID сообщения, от которого считаем время ответа

        async with AsyncSessionLocal() as session:
            # Найдем ВСЕ активные (неотвеченные, не удаленные) DBMessage от ЭТОГО КЛИЕНТА в ЭТОМ ЧАТЕ, 
            # которые были назначены ЭТОМУ ОТВЕЧАЮЩЕМУ СОТРУДНИКУ.
            # Нам нужно найти самое раннее из них для расчета времени ответа.
            all_pending_messages_for_this_employee_stmt = select(DBMessage).where(
                and_(
                    DBMessage.chat_id == chat_id,
                    DBMessage.client_telegram_id == client_telegram_id,
                    DBMessage.employee_id == responding_employee_id, # Только сообщения, назначенные этому сотруднику
                    DBMessage.responded_at.is_(None),
                    DBMessage.is_deleted == False
                )
            ).order_by(DBMessage.received_at.asc()) # Сортируем по возрастанию времени получения
            
            pending_messages_for_employee_result = await session.execute(all_pending_messages_for_this_employee_stmt)
            pending_db_messages_for_this_employee = pending_messages_for_employee_result.scalars().all()

            if pending_db_messages_for_this_employee:
                # Самое раннее сообщение этого клиента, назначенное этому сотруднику
                earliest_message_for_this_employee = pending_db_messages_for_this_employee[0]
                if earliest_message_for_this_employee.received_at:
                    calculated_response_time = (datetime.utcnow() - earliest_message_for_this_employee.received_at).total_seconds() / 60
                    time_response_anchor_message_id = earliest_message_for_this_employee.message_id # Telegram ID этого самого раннего сообщения
                    logger.info(f"⏱ Время ответа для сессии клиента {client_telegram_id} сотрудником {responding_employee_id}: {calculated_response_time:.1f} мин. (отсчет от сообщения Telegram ID: {time_response_anchor_message_id})")
            else:
                logger.warning(f"Не найдено активных сообщений от клиента {client_telegram_id} для сотрудника {responding_employee_id} для расчета времени ответа. Возможно, все уже обработано.")

            # Теперь найдем ВСЕ активные (неотвеченные, не удаленные) DBMessage от ЭТОГО КЛИЕНТА в ЭТОМ ЧАТЕ 
            # для ВСЕХ СОТРУДНИКОВ, чтобы пометить их как отвеченные.
            all_active_messages_from_client_globally_stmt = select(DBMessage).where(
                and_(
                    DBMessage.chat_id == chat_id,
                    DBMessage.client_telegram_id == client_telegram_id, # Все сообщения от этого клиента
                    DBMessage.responded_at.is_(None),
                    DBMessage.is_deleted == False
                )
            ).order_by(DBMessage.received_at.asc()) # Добавим сортировку, чтобы найти самое раннее для отмены уведомлений
            
            all_active_messages_result = await session.execute(all_active_messages_from_client_globally_stmt)
            all_active_db_messages_from_client_globally = all_active_messages_result.scalars().all()

            if not all_active_db_messages_from_client_globally:
                logger.info(f"⚠️ Не найдено активных неотвеченных сообщений от клиента ID {client_telegram_id} в чате {chat_id} для глобального обновления. Возможно, уже обработаны.")
                # Если calculated_response_time был вычислен (т.е. было сообщение для этого сотрудника), но глобальный список пуст,
                # это странно, но можно попробовать обновить хотя бы то, на которое ответили, если оно еще существует.
                # Эта логика может быть избыточной, если pending_db_messages_for_this_employee уже покрывает это.
                # Но оставлю для безопасности, если вдруг гонка состояний.
                if calculated_response_time is not None:
                    direct_reply_target_stmt = select(DBMessage).where(
                        and_(
                            DBMessage.chat_id == chat_id,
                            DBMessage.message_id == replied_to_client_message_telegram_id, 
                            DBMessage.employee_id == responding_employee_id,
                            DBMessage.responded_at.is_(None)
                        )
                    )
                    direct_reply_target_res = await session.execute(direct_reply_target_stmt)
                    direct_reply_target_db_msg = direct_reply_target_res.scalar_one_or_none()
                    if direct_reply_target_db_msg:
                        direct_reply_target_db_msg.responded_at = datetime.utcnow()
                        direct_reply_target_db_msg.answered_by_employee_id = responding_employee_id
                        direct_reply_target_db_msg.response_time_minutes = calculated_response_time
                        await self.notifications.cancel_notifications(direct_reply_target_db_msg.id)
                        await session.commit()
                        logger.info(f"✅ Обновлено (через запасной механизм) DBMessage.id {direct_reply_target_db_msg.id} для сотрудника {responding_employee_id}.")
                return

            updated_count = 0
            processed_client_message_telegram_ids_for_pending_removal = set()
            db_message_id_for_notification_cancel = None

            if all_active_db_messages_from_client_globally:
                # Определяем ID самого раннего сообщения в этой сессии (глобально для всех сотрудников)
                # Уведомления должны были быть запланированы только для него (для каждой копии сотрудника)
                # Однако, текущая логика NotificationService хранит задачи по DBMessage.id (уникальный PK)
                # Если мы перешли на новую логику планирования (только для первого сообщения сессии для КАЖДОГО сотрудника),
                # то отмена должна быть более таргетированной.

                # Найдем все УНИКАЛЬНЫЕ DBMessage.id, для которых МОГЛИ БЫТЬ запланированы уведомления
                # по новой логике (т.е. это были первые сообщения сессии для каждого сотрудника)
                # Это будут все all_active_db_messages_from_client_globally, т.к. для каждого из них (для его employee_id)
                # track_message решал, планировать или нет.
                # При ответе мы должны отменить ВСЕ активные уведомления для этого клиента в этом чате.
                # Поэтому проходим по всем и отменяем.
                pass # Эта логика остается прежней - отменяем для всех обновляемых db_message_to_update.id

            for db_message_to_update in all_active_db_messages_from_client_globally:
                db_message_to_update.responded_at = datetime.utcnow()
                db_message_to_update.answered_by_employee_id = responding_employee_id
                processed_client_message_telegram_ids_for_pending_removal.add(db_message_to_update.message_id) 

                # Время ответа (calculated_response_time, посчитанное от САМОГО РАННЕГО сообщения клиента для ЭТОГО СОТРУДНИКА) 
                # записываем только для той записи DBMessage, которая принадлежит ЭТОМУ ОТВЕТИВШЕМУ СОТРУДНИКУ 
                # и соответствует тому сообщению, НА КОТОРОЕ ОН НЕПОСРЕДСТВЕННО ОТВЕТИЛ (replied_to_client_message_telegram_id).
                # Это гарантирует, что response_time ставится только один раз за сессию ответа сотрудника.
                if db_message_to_update.employee_id == responding_employee_id and \
                   db_message_to_update.message_id == replied_to_client_message_telegram_id and \
                   calculated_response_time is not None:
                    db_message_to_update.response_time_minutes = calculated_response_time
                    logger.info(f"⏱ -> Записано время ответа {calculated_response_time:.1f} мин для DBMessage.id {db_message_to_update.id} (сотрудник {responding_employee_id}, ответил на Telegram ID {replied_to_client_message_telegram_id}). Отсчет от Telegram ID {time_response_anchor_message_id}.")
                \
                updated_count += 1
                await self.notifications.cancel_notifications(db_message_to_update.id)
            
            await session.commit()
            logger.info(f"✅ Обновлено {updated_count} DBMessage записей для сессии клиента ID {client_telegram_id} в чате {chat_id}. Ответил: сотрудник ID {responding_employee_id}.")

        # Удаляем из отслеживаемых `pending_messages` все обработанные сообщения этого клиента
        # self.pending_messages теперь не так критичен, если уведомления планируются по-новому
        if chat_id in self.pending_messages:
            client_messages_in_pending_keys = list(self.pending_messages[chat_id].keys())
            removed_from_pending_count = 0
            for client_message_telegram_id_key in client_messages_in_pending_keys:
                if client_message_telegram_id_key in processed_client_message_telegram_ids_for_pending_removal:
                    del self.pending_messages[chat_id][client_message_telegram_id_key]
                    removed_from_pending_count +=1
            
            if removed_from_pending_count > 0:
                logger.info(f"🗑 Удалено {removed_from_pending_count} записей из pending_messages для чата {chat_id} (клиент {client_telegram_id}).")
            
            if not self.pending_messages[chat_id]: 
                del self.pending_messages[chat_id]
                logger.info(f"🗑 Удален ключ чата {chat_id} из pending_messages, т.к. он пуст.")
    
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
        # Проверяем, является ли отправитель сообщения сотрудником
        sender_employee_result = await session.execute(
            select(Employee).where(Employee.telegram_id == message.from_user.id)
        )
        sender_is_employee = sender_employee_result.scalar_one_or_none() is not None

    # Проверяем, является ли сообщение ответом
    if message.reply_to_message:
        if sender_is_employee:
            # Это ответ сотрудника на какое-то сообщение
            logger.info(f"💬 Ответ от сотрудника: {message.from_user.full_name}")
            
            # Получаем информацию об ответившем сотруднике (для employee_id)
            responding_employee_result = await session.execute(
                select(Employee).where(and_(Employee.telegram_id == message.from_user.id, Employee.is_active == True))
            )
            responding_employee = responding_employee_result.scalar_one_or_none()
            
            if responding_employee:
                # Убедимся, что ответ был на сообщение клиента, а не другого сотрудника
                if message.reply_to_message.from_user:
                    # Проверим, не является ли автор исходного сообщения тоже сотрудником
                    original_sender_employee_result = await session.execute(
                        select(Employee).where(Employee.telegram_id == message.reply_to_message.from_user.id)
                    )
                    original_sender_is_employee = original_sender_employee_result.scalar_one_or_none() is not None
                    
                    if original_sender_is_employee:
                        logger.info(f"👨‍💼 Сотрудник {responding_employee.full_name} ответил на сообщение другого сотрудника. Игнорируем для статистики ответа.")
                        return # Не трекаем ответ сотрудника на сотрудника

                    await message_tracker.mark_as_responded(message, responding_employee.id)
                    logger.info(f"✅ Отмечен ответ сотрудника: {responding_employee.full_name}")
                else:
                    logger.info(f"⚠️ Сотрудник {message.from_user.full_name} (ID: {message.from_user.id}) не найден или неактивен. Ответ не засчитан.")
            else:
                # Это ответ НЕ сотрудника (например, клиент отвечает клиенту, или бот отвечает). Игнорируем.
                logger.info(f"👤 Ответ от НЕ сотрудника ({message.from_user.full_name}). Игнорируем.")
                return
        else: # Это новое сообщение (не ответ)
            if sender_is_employee:
                # Новое сообщение от сотрудника - просто логируем и игнорируем для трекинга
                logger.info(f"🗣️ Новое сообщение от сотрудника {message.from_user.full_name} в группе. Не для отслеживания.")
                return
    else:
        # Это новое сообщение от клиента
        logger.info(f"📨 Новое сообщение от клиента: {message.from_user.full_name}")
        active_employees_result = await session.execute(
                select(Employee).where(Employee.is_active == True)
            )
        active_employees = active_employees_result.scalars().all()
        
        if not active_employees:
            logger.warning(f"Нет активных сотрудников для назначения сообщения от клиента {message.from_user.full_name}")
            return

        for employee_obj in active_employees:
            await message_tracker.track_message(message, employee_obj.id)
            logger.info(f"📊 Трекаем сообщение для сотрудника: {employee_obj.full_name} (ID: {employee_obj.id})")


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