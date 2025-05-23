from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Dict, Any
from pydantic import BaseModel

from database.database import get_db
from database.models import SystemSettings
from web.auth import get_current_admin

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    notification_delay_1: int
    notification_delay_2: int  
    notification_delay_3: int
    notifications_enabled: bool
    daily_reports_enabled: bool
    daily_reports_time: str


@router.get("/")
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_admin = Depends(get_current_admin)
) -> Dict[str, Any]:
    """Получение всех настроек системы"""
    
    result = await db.execute(select(SystemSettings))
    settings = result.scalars().all()
    
    settings_dict = {setting.key: setting.value for setting in settings}
    
    # Значения по умолчанию, если настройки не найдены
    default_settings = {
        "notification_delay_1": "15",
        "notification_delay_2": "30", 
        "notification_delay_3": "60",
        "notifications_enabled": "true",
        "daily_reports_enabled": "true",
        "daily_reports_time": "18:00"
    }
    
    # Заполняем отсутствующие настройки значениями по умолчанию
    for key, default_value in default_settings.items():
        if key not in settings_dict:
            settings_dict[key] = default_value
    
    # Преобразуем типы для фронтенда
    return {
        "notification_delay_1": int(settings_dict["notification_delay_1"]),
        "notification_delay_2": int(settings_dict["notification_delay_2"]),
        "notification_delay_3": int(settings_dict["notification_delay_3"]),
        "notifications_enabled": settings_dict["notifications_enabled"].lower() == "true",
        "daily_reports_enabled": settings_dict["daily_reports_enabled"].lower() == "true",
        "daily_reports_time": settings_dict["daily_reports_time"]
    }


@router.put("/")
async def update_settings(
    settings_data: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin = Depends(get_current_admin)
):
    """Обновление настроек системы"""
    
    # Валидация значений
    if settings_data.notification_delay_1 <= 0 or settings_data.notification_delay_1 > 120:
        raise HTTPException(status_code=400, detail="Первое уведомление должно быть от 1 до 120 минут")
    
    if settings_data.notification_delay_2 <= settings_data.notification_delay_1 or settings_data.notification_delay_2 > 180:
        raise HTTPException(status_code=400, detail="Второе уведомление должно быть больше первого и не более 180 минут")
        
    if settings_data.notification_delay_3 <= settings_data.notification_delay_2 or settings_data.notification_delay_3 > 300:
        raise HTTPException(status_code=400, detail="Третье уведомление должно быть больше второго и не более 300 минут")
    
    # Формируем данные для обновления
    settings_to_update = {
        "notification_delay_1": str(settings_data.notification_delay_1),
        "notification_delay_2": str(settings_data.notification_delay_2),
        "notification_delay_3": str(settings_data.notification_delay_3),
        "notifications_enabled": str(settings_data.notifications_enabled).lower(),
        "daily_reports_enabled": str(settings_data.daily_reports_enabled).lower(),
        "daily_reports_time": settings_data.daily_reports_time
    }
    
    # Обновляем или создаем настройки
    for key, value in settings_to_update.items():
        result = await db.execute(
            select(SystemSettings).where(SystemSettings.key == key)
        )
        setting = result.scalar_one_or_none()
        
        if setting:
            setting.value = value
        else:
            setting = SystemSettings(key=key, value=value)
            db.add(setting)
    
    await db.commit()
    
    return {"message": "Настройки успешно обновлены"}


@router.post("/reset")
async def reset_settings(
    db: AsyncSession = Depends(get_db),
    current_admin = Depends(get_current_admin)
):
    """Сброс настроек к значениям по умолчанию"""
    
    default_settings = {
        "notification_delay_1": "15",
        "notification_delay_2": "30",
        "notification_delay_3": "60", 
        "notifications_enabled": "true",
        "daily_reports_enabled": "true",
        "daily_reports_time": "18:00"
    }
    
    for key, value in default_settings.items():
        result = await db.execute(
            select(SystemSettings).where(SystemSettings.key == key)
        )
        setting = result.scalar_one_or_none()
        
        if setting:
            setting.value = value
        else:
            setting = SystemSettings(key=key, value=value)
            db.add(setting)
    
    await db.commit()
    
    return {"message": "Настройки сброшены к значениям по умолчанию"} 