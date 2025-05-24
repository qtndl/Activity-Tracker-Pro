from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import logging
from .settings_manager import settings_manager

logger = logging.getLogger(__name__)

# Глобальная переменная для хранения планировщика
global_scheduler = None
global_message_tracker = None


async def setup_scheduler(message_tracker):
    """Настройка планировщика задач"""
    global global_scheduler, global_message_tracker
    
    scheduler = AsyncIOScheduler()
    global_scheduler = scheduler
    global_message_tracker = message_tracker
    
    # Получаем время отправки отчетов из настроек
    daily_time = await settings_manager.get_daily_reports_time()
    hour, minute = map(int, daily_time.split(':'))
    
    # Ежедневные отчеты сотрудникам (время из настроек)
    # Статистика считается в реальном времени, предварительный расчет не нужен
    scheduler.add_job(
        send_daily_reports,
        CronTrigger(hour=hour, minute=minute),
        args=[message_tracker],
        id='daily_reports',
        replace_existing=True
    )
    
    # Запуск планировщика
    scheduler.start()
    logger.info(f"✅ Планировщик задач запущен. Ежедневные отчеты: {daily_time}")
    
    return scheduler


async def update_daily_reports_time():
    """Обновление времени ежедневных отчетов в планировщике"""
    global global_scheduler, global_message_tracker
    
    if global_scheduler is None or global_message_tracker is None:
        logger.warning("Планировщик не инициализирован")
        return
    
    try:
        # Получаем новое время из настроек
        daily_time = await settings_manager.get_daily_reports_time()
        hour, minute = map(int, daily_time.split(':'))
        
        # Обновляем задачу с новым временем
        global_scheduler.add_job(
            send_daily_reports,
            CronTrigger(hour=hour, minute=minute),
            args=[global_message_tracker],
            id='daily_reports',
            replace_existing=True  # Заменяем существующую задачу
        )
        
        logger.info(f"Время ежедневных отчетов обновлено на {daily_time}")
        
    except Exception as e:
        logger.error(f"Ошибка при обновлении времени отчетов: {e}")


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