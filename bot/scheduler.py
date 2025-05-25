from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import logging
from .settings_manager import settings_manager
from web.services.statistics_service import StatisticsService

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
        stats_service = StatisticsService(session)
        
        # Получаем всех активных сотрудников
        active_employees_result = await session.execute(
            select(Employee).where(Employee.is_active == True)
        )
        active_employees = active_employees_result.scalars().all()
        
        individual_employee_stats_list = []
        
        for employee in active_employees:
            try:
                # Получаем статистику сотрудника через StatisticsService
                employee_stats_obj = await stats_service.get_employee_stats(employee.id, period="today")
                if employee_stats_obj:
                    individual_employee_stats_list.append(employee_stats_obj)
                # Отправляем отчет сотруднику
                    await message_tracker.notifications.send_daily_report(employee.id, employee_stats_obj)
            except Exception as e:
                logger.error(f"Ошибка при получении/отправке отчета для сотрудника {employee.id}: {e}")
        
        # Отправляем общий отчет администраторам
        admin_result = await session.execute(
            select(Employee).where(
                Employee.is_admin == True,
                Employee.is_active == True
            )
        )
        admins = admin_result.scalars().all()
        logger.info(f"[SCHEDULER_DEBUG] Found {len(admins)} admin(s) to send reports to.")
        
        if admins:
            try:
                # Получаем корректную общую статистику для админов
                admin_user_id_for_overview = admins[0].id 
                admin_summary_stats = await stats_service.get_dashboard_overview(user_id=admin_user_id_for_overview, is_admin=True, period="today")
                for admin in admins:
                    # Передаем и общую сводку, и детализацию по каждому сотруднику
                    await message_tracker.notifications.send_admin_report(admin.telegram_id, admin_summary_stats, individual_employee_stats_list)
            except Exception as e:
                logger.error(f"Ошибка при подготовке или отправке общего отчета администраторам: {e}") 