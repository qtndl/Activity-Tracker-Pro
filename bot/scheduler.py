from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import logging
from .settings_manager import settings_manager

logger = logging.getLogger(__name__)


async def setup_scheduler(message_tracker):
    """Настройка планировщика задач"""
    scheduler = AsyncIOScheduler()
    
    # Получаем время отправки отчетов из настроек
    daily_time = await settings_manager.get_daily_reports_time()
    hour, minute = map(int, daily_time.split(':'))
    
    # Ежедневный расчет статистики в 00:01
    scheduler.add_job(
        message_tracker.analytics.calculate_daily_stats,
        CronTrigger(hour=0, minute=1),
        id='daily_stats',
        replace_existing=True
    )
    
    # Еженедельный расчет статистики по понедельникам в 00:05
    scheduler.add_job(
        message_tracker.analytics.calculate_weekly_stats,
        CronTrigger(day_of_week=0, hour=0, minute=5),
        id='weekly_stats',
        replace_existing=True
    )
    
    # Ежемесячный расчет статистики 1-го числа в 00:10
    scheduler.add_job(
        message_tracker.analytics.calculate_monthly_stats,
        CronTrigger(day=1, hour=0, minute=10),
        id='monthly_stats',
        replace_existing=True
    )
    
    # Ежедневные отчеты сотрудникам (время из настроек)
    scheduler.add_job(
        send_daily_reports,
        CronTrigger(hour=hour, minute=minute),
        args=[message_tracker],
        id='daily_reports',
        replace_existing=True
    )
    
    # Запуск планировщика
    scheduler.start()
    logger.info(f"Планировщик задач запущен. Ежедневные отчеты: {daily_time}")
    
    return scheduler


async def send_daily_reports(message_tracker):
    """Отправка ежедневных отчетов"""
    from database.database import AsyncSessionLocal
    from database.models import Employee
    from sqlalchemy import select
    
    async with AsyncSessionLocal() as session:
        # Получаем всех активных сотрудников
        result = await session.execute(
            select(Employee).where(Employee.is_active == True)
        )
        employees = result.scalars().all()
        
        all_stats = []
        
        for employee in employees:
            stats = await message_tracker.analytics.get_employee_stats(employee.id, 'daily')
            if stats:
                # Добавляем employee_id к статистике для админского отчета
                stats['employee_id'] = employee.id
                all_stats.append(stats)
                # Отправляем отчет сотруднику
                await message_tracker.notifications.send_daily_report(employee.id, stats)
        
        # Отправляем общий отчет администраторам
        admin_result = await session.execute(
            select(Employee).where(
                Employee.is_admin == True,
                Employee.is_active == True
            )
        )
        admins = admin_result.scalars().all()
        
        for admin in admins:
            await message_tracker.notifications.send_admin_report(admin.telegram_id, all_stats) 