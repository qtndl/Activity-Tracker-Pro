from aiogram import Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from database.database import AsyncSessionLocal
from database.models import Employee, Message as DBMessage
from .scheduler import setup_scheduler


def register_handlers(dp: Dispatcher, message_tracker):
    """Регистрация всех обработчиков"""
    
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
                text += f"📨 Всего сообщений: {stats.total_messages}\n"
                text += f"✅ Отвечено: {stats.responded_messages}\n"
                text += f"❌ Пропущено: {stats.missed_messages}\n"
                
                if stats.responded_messages > 0:
                    text += f"\n⏱ Среднее время ответа: {stats.avg_response_time:.1f} мин\n"
                    text += f"\n⚠️ Превышений времени ответа:\n"
                    text += f"  • Более 15 мин: {stats.exceeded_15_min}\n"
                    text += f"  • Более 30 мин: {stats.exceeded_30_min}\n"
                    text += f"  • Более 1 часа: {stats.exceeded_60_min}"
                
                # Расчет эффективности
                if stats.total_messages > 0:
                    efficiency = (stats.responded_messages / stats.total_messages) * 100
                    text += f"\n\n📈 Эффективность: {efficiency:.1f}%"
            else:
                text = "📊 Статистика за неделю пока отсутствует"
            
            await message.answer(text, parse_mode="HTML")
    
    @dp.message(Command("report_monthly"))
    async def monthly_report_command(message: Message):
        """Месячный отчет - ТОЛЬКО в личных сообщениях"""
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
                text += f"📨 Всего сообщений: {stats.total_messages}\n"
                text += f"✅ Отвечено: {stats.responded_messages}\n"
                text += f"❌ Пропущено: {stats.missed_messages}\n"
                
                if stats.responded_messages > 0:
                    text += f"\n⏱ Среднее время ответа: {stats.avg_response_time:.1f} мин\n"
                    text += f"\n⚠️ Превышений времени ответа:\n"
                    text += f"  • Более 15 мин: {stats.exceeded_15_min}\n"
                    text += f"  • Более 30 мин: {stats.exceeded_30_min}\n"
                    text += f"  • Более 1 часа: {stats.exceeded_60_min}"
                
                # Расчет эффективности и средних показателей
                if stats.total_messages > 0:
                    efficiency = (stats.responded_messages / stats.total_messages) * 100
                    avg_daily = stats.total_messages / 30  # Примерно
                    
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
            
            for employee in employees:
                stats = await message_tracker.analytics.get_employee_stats(employee.id, 'daily')
                
                if stats:
                    text += f"👤 <b>{employee.full_name}</b>\n"
                    text += f"  📨 Сообщений: {stats['total_messages']}\n"
                    text += f"  ✅ Отвечено: {stats['responded_messages']}\n"
                    text += f"  ❌ Пропущено: {stats['missed_messages']}\n"
                    
                    if stats.get('deleted_messages', 0) > 0:
                        text += f"  🗑 Удалено: {stats['deleted_messages']}\n"
                    
                    if stats['responded_messages'] > 0:
                        text += f"  ⏱ Среднее время: {stats['avg_response_time']:.1f} мин\n"
                    
                    text += "\n"
                    
                    total_messages += stats['total_messages']
                    total_responded += stats['responded_messages']
                    total_missed += stats['missed_messages']
                    total_deleted += stats.get('deleted_messages', 0)
            
            text += f"\n📊 <b>Итого:</b>\n"
            text += f"📨 Всего сообщений: {total_messages}\n"
            text += f"✅ Отвечено: {total_responded}\n"
            text += f"❌ Пропущено: {total_missed}\n"
            
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


async def register_handlers_and_scheduler(dp: Dispatcher, message_tracker):
    """Регистрация обработчиков и запуск планировщика"""
    register_handlers(dp, message_tracker)
    
    # Настройка планировщика задач (теперь async)
    scheduler = await setup_scheduler(message_tracker)
    return scheduler 