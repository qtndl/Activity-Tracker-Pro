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
        self.pending_messages = {}  # {chat_id: {message_id: (employee_id, received_at)}}
        self.analytics = AnalyticsService()
        self.notifications = NotificationService(bot)
    
    async def track_message(self, message: Message, employee_id: int):
        """Отслеживание входящего сообщения от клиента"""
        chat_id = message.chat.id
        message_id = message.message_id
        
        if chat_id not in self.pending_messages:
            self.pending_messages[chat_id] = {}
        
        self.pending_messages[chat_id][message_id] = (employee_id, datetime.utcnow())
        
        # Сохраняем в БД
        async with AsyncSessionLocal() as session:
            db_message = DBMessage(
                employee_id=employee_id,
                chat_id=chat_id,
                message_id=message_id,
                client_telegram_id=message.from_user.id,
                client_username=message.from_user.username,
                client_name=message.from_user.full_name,
                message_text=message.text,
                received_at=datetime.utcnow()
            )
            session.add(db_message)
            await session.commit()
            
            # Запускаем таймеры для уведомлений
            await self.schedule_notifications(db_message.id, employee_id, chat_id)
    
    async def mark_as_responded(self, message: Message, employee_id: int):
        """Отметка сообщения как отвеченного"""
        chat_id = message.chat.id
        
        if chat_id in self.pending_messages:
            # Находим последнее неотвеченное сообщение в этом чате
            for msg_id, (emp_id, received_at) in list(self.pending_messages[chat_id].items()):
                if emp_id == employee_id:
                    response_time = (datetime.utcnow() - received_at).total_seconds() / 60
                    
                    # Обновляем в БД
                    async with AsyncSessionLocal() as session:
                        result = await session.execute(
                            select(DBMessage).where(
                                and_(
                                    DBMessage.chat_id == chat_id,
                                    DBMessage.message_id == msg_id,
                                    DBMessage.employee_id == employee_id
                                )
                            )
                        )
                        db_message = result.scalar_one_or_none()
                        
                        if db_message:
                            db_message.responded_at = datetime.utcnow()
                            db_message.response_time_minutes = response_time
                            await session.commit()
                    
                    # Удаляем из отслеживаемых
                    del self.pending_messages[chat_id][msg_id]
                    
                    # Отменяем запланированные уведомления
                    await self.notifications.cancel_notifications(msg_id)
    
    async def mark_as_deleted(self, chat_id: int, message_id: int):
        """Отметка сообщения как удаленного"""
        logger.info(f"🗑 Сообщение {message_id} удалено в чате {chat_id}")
        
        # Обновляем в БД
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(DBMessage).where(
                    and_(
                        DBMessage.chat_id == chat_id,
                        DBMessage.message_id == message_id
                    )
                )
            )
            db_messages = result.scalars().all()
            
            for db_message in db_messages:
                if not db_message.is_deleted:  # Если еще не помечено как удаленное
                    db_message.is_deleted = True
                    db_message.deleted_at = datetime.utcnow()
                    
                    # Отменяем уведомления для удаленного сообщения
                    await self.notifications.cancel_notifications(db_message.id)
                    
                    logger.info(f"✅ Сообщение {message_id} помечено как удаленное для сотрудника {db_message.employee_id}")
            
            await session.commit()
        
        # Удаляем из отслеживаемых
        if chat_id in self.pending_messages and message_id in self.pending_messages[chat_id]:
            del self.pending_messages[chat_id][message_id]
    
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
        
        stats = await message_tracker.analytics.get_employee_stats(employee.id, 'daily')
        
        if stats:
            text = f"📊 Ваша статистика за сегодня:\n\n"
            text += f"📨 Всего сообщений: {stats['total_messages']}\n"
            text += f"✅ Отвечено: {stats['responded_messages']}\n"
            text += f"❌ Пропущено: {stats['missed_messages']}\n"
            
            # Добавляем информацию об удаленных сообщениях если они есть
            if stats.get('deleted_messages', 0) > 0:
                text += f"🗑 Удалено клиентами: {stats['deleted_messages']}\n"
            
            text += f"👥 Уникальных клиентов: {stats['unique_clients']}\n"
            text += f"⏱ Среднее время ответа: {stats['avg_response_time']:.1f} мин\n"
            text += f"⚠️ Ответов > 15 мин: {stats['exceeded_15_min']}\n"
            text += f"⚠️ Ответов > 30 мин: {stats['exceeded_30_min']}\n"
            text += f"⚠️ Ответов > 60 мин: {stats['exceeded_60_min']}"
            
            # Добавляем примечание об удаленных сообщениях
            if stats.get('deleted_messages', 0) > 0:
                text += f"\n\n💡 <i>Удаленные клиентами сообщения не считаются пропущенными</i>"
        else:
            text = "📊 Статистика за сегодня пока отсутствует"
        
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
        logger.info(f"🚫 Игнорируем системное сообщение в чате {message.chat.id}")
        return
    
    logger.info(f"📩 Обрабатываем сообщение от {message.from_user.full_name} в чате {message.chat.id}")
    
    # Проверяем, является ли сообщение ответом
    if message.reply_to_message:
        # Это ответ сотрудника
        logger.info(f"💬 Ответ сотрудника: {message.from_user.full_name}")
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Employee).where(Employee.telegram_id == message.from_user.id)
            )
            employee = result.scalar_one_or_none()
            
            if employee and employee.is_active:
                await message_tracker.mark_as_responded(message, employee.id)
                logger.info(f"✅ Отмечен ответ сотрудника: {employee.full_name}")
            else:
                logger.info(f"⚠️ Пользователь {message.from_user.full_name} не найден среди сотрудников")
    else:
        # Это новое сообщение от клиента
        logger.info(f"📨 Новое сообщение от клиента: {message.from_user.full_name}")
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Employee).where(Employee.is_active == True)
            )
            employees = result.scalars().all()
            
            for employee in employees:
                await message_tracker.track_message(message, employee.id)
                logger.info(f"📊 Трекаем сообщение для сотрудника: {employee.full_name}")


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