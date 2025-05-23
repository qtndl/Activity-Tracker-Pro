"""Модуль для получения настроек системы из базы данных"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database.database import AsyncSessionLocal
from database.models import SystemSettings
from typing import Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)


class SettingsManager:
    """Менеджер настроек системы"""
    
    def __init__(self):
        self._cache = {}
        self._cache_timeout = 300  # 5 минут кэша
        self._last_update = 0
    
    async def get_notification_delays(self) -> Tuple[int, int, int]:
        """Получить задержки для уведомлений в минутах"""
        settings = await self._get_settings()
        
        delay1 = int(settings.get("notification_delay_1", "15"))
        delay2 = int(settings.get("notification_delay_2", "30"))
        delay3 = int(settings.get("notification_delay_3", "60"))
        
        return delay1, delay2, delay3
    
    async def get_notification_settings(self) -> Dict[str, bool]:
        """Получить настройки уведомлений"""
        settings = await self._get_settings()
        
        return {
            "notifications_enabled": settings.get("notifications_enabled", "true").lower() == "true",
            "daily_reports_enabled": settings.get("daily_reports_enabled", "true").lower() == "true"
        }
    
    async def get_daily_reports_time(self) -> str:
        """Получить время отправки ежедневных отчетов"""
        settings = await self._get_settings()
        return settings.get("daily_reports_time", "18:00")
    
    async def notifications_enabled(self) -> bool:
        """Проверить включены ли уведомления"""
        settings = await self.get_notification_settings()
        return settings["notifications_enabled"]
    
    async def daily_reports_enabled(self) -> bool:
        """Проверить включены ли ежедневные отчеты"""
        settings = await self.get_notification_settings()
        return settings["daily_reports_enabled"]
    
    async def _get_settings(self) -> Dict[str, str]:
        """Получить все настройки из базы данных с кэшированием"""
        import time
        current_time = time.time()
        
        # Проверяем кэш
        if self._cache and (current_time - self._last_update) < self._cache_timeout:
            return self._cache
        
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(SystemSettings))
                settings = result.scalars().all()
                
                self._cache = {setting.key: setting.value for setting in settings}
                self._last_update = current_time
                
                logger.info(f"Настройки обновлены из БД: {len(self._cache)} параметров")
                return self._cache
                
        except Exception as e:
            logger.error(f"Ошибка при получении настроек: {e}")
            
            # Возвращаем настройки по умолчанию при ошибке
            return {
                "notification_delay_1": "15",
                "notification_delay_2": "30", 
                "notification_delay_3": "60",
                "notifications_enabled": "true",
                "daily_reports_enabled": "true",
                "daily_reports_time": "18:00"
            }
    
    def clear_cache(self):
        """Очистить кэш настроек"""
        self._cache = {}
        self._last_update = 0
        logger.info("Кэш настроек очищен")


# Глобальный экземпляр менеджера настроек
settings_manager = SettingsManager() 