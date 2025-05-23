from aiogram import Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from database.database import AsyncSessionLocal
from database.models import Employee
from .scheduler import setup_scheduler


def register_handlers(dp: Dispatcher, message_tracker):
    """Регистрация всех обработчиков"""
    
    @dp.message(Command("help"))
    async def help_command(message: Message):
        """Помощь по командам"""
        help_text = """
🤖 <b>Доступные команды:</b>

/start - Начало работы и вход в веб-панель
/stats - Показать вашу статистику за сегодня
/report_weekly - Недельный отчет
/report_monthly - Месячный отчет
/help - Это сообщение

<b>Как работает бот:</b>
• Бот автоматически отслеживает сообщения в группах
• Отправляет уведомления при долгом отсутствии ответа
• Собирает статистику по времени ответов
• Формирует отчеты для анализа работы

<b>Веб-панель:</b>
Используйте /start для получения ссылки на вход
        """
        await message.answer(help_text, parse_mode="HTML")
    
    @dp.message(Command("report_weekly"))
    async def weekly_report_command(message: Message):
        """Недельный отчет"""
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
        """Месячный отчет"""
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
        """Статистика для администратора"""
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
            
            for employee in employees:
                stats = await message_tracker.analytics.get_employee_stats(employee.id, 'daily')
                
                if stats:
                    text += f"👤 <b>{employee.full_name}</b>\n"
                    text += f"  📨 Сообщений: {stats.total_messages}\n"
                    text += f"  ✅ Отвечено: {stats.responded_messages}\n"
                    text += f"  ❌ Пропущено: {stats.missed_messages}\n"
                    
                    if stats.responded_messages > 0:
                        text += f"  ⏱ Среднее время: {stats.avg_response_time:.1f} мин\n"
                    
                    text += "\n"
                    
                    total_messages += stats.total_messages
                    total_responded += stats.responded_messages
                    total_missed += stats.missed_messages
            
            text += f"\n📊 <b>Итого:</b>\n"
            text += f"📨 Всего сообщений: {total_messages}\n"
            text += f"✅ Отвечено: {total_responded}\n"
            text += f"❌ Пропущено: {total_missed}\n"
            
            if total_messages > 0:
                overall_efficiency = (total_responded / total_messages) * 100
                text += f"📈 Общая эффективность: {overall_efficiency:.1f}%"
            
            await message.answer(text, parse_mode="HTML")
    
    # Настройка планировщика задач
    setup_scheduler(message_tracker) 