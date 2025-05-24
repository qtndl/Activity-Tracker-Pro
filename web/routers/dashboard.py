from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime, timedelta
from pydantic import BaseModel

from database.database import get_db
from database.models import Employee, Message, SystemSettings
from web.auth import get_current_user, get_current_admin
from web.services.statistics_service import StatisticsService
from web.services.google_sheets import GoogleSheetsService
from config.config import settings

router = APIRouter()


class DashboardSettings(BaseModel):
    google_sheets_enabled: bool
    
    
@router.get("/overview")
async def get_dashboard_overview(
    period: str = Query("today", regex="^(today|week|month)$"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Получить обзор для дашборда - ЕДИНЫЙ ИСТОЧНИК ДАННЫХ"""
    
    # Используем единый сервис статистики
    stats_service = StatisticsService(db)
    
    return await stats_service.get_dashboard_overview(
        user_id=current_user.get('employee_id'),
        is_admin=current_user.get('is_admin', False),
        period=period
    )


@router.get("/settings")
async def get_dashboard_settings(
    current_user: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
) -> DashboardSettings:
    """Получить настройки дашборда (только для админов)"""
    
    # Получаем настройки из базы
    result = await db.execute(
        select(SystemSettings).where(SystemSettings.key == "google_sheets_enabled")
    )
    setting = result.scalar_one_or_none()
    
    google_sheets_enabled = setting and setting.value.lower() == "true" if setting else False
    
    return DashboardSettings(
        google_sheets_enabled=google_sheets_enabled
    )


@router.post("/settings")
async def update_dashboard_settings(
    settings_data: DashboardSettings,
    current_user: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Обновить настройки дашборда (только для админов)"""
    
    # Обновляем или создаем настройку Google Sheets
    result = await db.execute(
        select(SystemSettings).where(SystemSettings.key == "google_sheets_enabled")
    )
    setting = result.scalar_one_or_none()
    
    if setting:
        setting.value = "true" if settings_data.google_sheets_enabled else "false"
        setting.updated_at = datetime.utcnow()
    else:
        setting = SystemSettings(
            key="google_sheets_enabled",
            value="true" if settings_data.google_sheets_enabled else "false",
            description="Включить экспорт в Google Sheets"
        )
        db.add(setting)
    
    await db.commit()
    
    return {"message": "Настройки успешно сохранены"}


@router.post("/export/google-sheets")
async def export_to_google_sheets(
    period: str = Query("today", regex="^(today|week|month)$"),
    current_user: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Экспортировать статистику в Google Sheets (только для админов) - ЕДИНЫЙ ИСТОЧНИК ДАННЫХ"""
    
    # Проверяем что Google Sheets включен
    sheets_service = GoogleSheetsService()
    if not await sheets_service.is_enabled():
        raise HTTPException(
            status_code=400,
            detail="Google Sheets интеграция отключена"
        )
    
    # Используем единый сервис статистики
    stats_service = StatisticsService(db)
    all_stats = await stats_service.get_all_employees_stats(period=period)
    
    # Формируем данные для экспорта
    data = [["Сотрудник", "Всего сообщений", "Отвечено", "Пропущено", 
             "Среднее время ответа (мин)", "Эффективность (%)"]]
    
    for stats in all_stats:
        data.append([
            stats.employee_name,
            stats.total_messages,
            stats.responded_messages,
            stats.missed_messages,
            round(stats.avg_response_time or 0, 1),
            round(stats.efficiency_percent, 1)
        ])
    
    # Название листа с датой
    sheet_name = f"Statistics_{period}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    
    # Экспортируем в Google Sheets
    try:
        sheet_url = await sheets_service.export_statistics(data, sheet_name)
        return {
            "message": "Данные успешно экспортированы",
            "sheet_url": sheet_url
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка экспорта: {str(e)}"
        ) 