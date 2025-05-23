"""Безопасная авторизация через Telegram с двухфакторной проверкой"""

import hashlib
import hmac
import json
import os
import random
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict

from fastapi import APIRouter, Request, HTTPException, Depends, Form, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import aiohttp

from database.database import get_db
from database.models import Employee
from web.auth import create_access_token, get_current_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Получаем токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN", "8110382002:AAHuWex2O-QvW7ElqyOMu1ZHJEGiS8dSGmE")

# Временное хранилище кодов {telegram_id: {"code": "123456", "expires": datetime, "attempts": 0}}
verification_codes: Dict[int, dict] = {}

# Модели запросов
class SendCodeRequest(BaseModel):
    telegram_id: int

class VerifyCodeRequest(BaseModel):
    telegram_id: int
    code: str


async def send_telegram_message(telegram_id: int, message: str) -> bool:
    """Отправляет сообщение пользователю через Telegram Bot API"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={
                "chat_id": telegram_id,
                "text": message,
                "parse_mode": "HTML"
            }) as response:
                result = await response.json()
                return result.get("ok", False)
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения {telegram_id}: {e}")
        return False


def generate_verification_code() -> str:
    """Генерирует 6-значный код подтверждения"""
    return f"{random.randint(100000, 999999)}"


def cleanup_expired_codes():
    """Удаляет истекшие коды"""
    now = datetime.utcnow()
    expired_ids = []
    
    for telegram_id, data in verification_codes.items():
        if data["expires"] < now:
            expired_ids.append(telegram_id)
    
    for telegram_id in expired_ids:
        del verification_codes[telegram_id]


@router.post("/send-code")
async def send_verification_code(
    request: SendCodeRequest,
    db: AsyncSession = Depends(get_db)
):
    """Отправляет код подтверждения в Telegram"""
    
    # Очищаем истекшие коды
    cleanup_expired_codes()
    
    telegram_id = request.telegram_id
    
    # Проверяем, что пользователь существует в системе
    result = await db.execute(
        select(Employee).where(Employee.telegram_id == telegram_id)
    )
    employee = result.scalar_one_or_none()
    
    if not employee:
        logger.warning(f"Попытка получить код для несуществующего пользователя {telegram_id}")
        return {
            "success": False,
            "error": "Пользователь не найден",
            "message": f"Telegram ID {telegram_id} не зарегистрирован в системе. Обратитесь к администратору."
        }
    
    if not employee.is_active:
        logger.warning(f"Попытка получить код для деактивированного пользователя {employee.full_name}")
        return {
            "success": False,
            "error": "Аккаунт деактивирован", 
            "message": "Ваш аккаунт временно деактивирован. Обратитесь к администратору."
        }
    
    # Проверяем лимит попыток (не более 3 кодов в час)
    now = datetime.utcnow()
    recent_attempts = [
        data for data in verification_codes.values() 
        if data.get("created", now) > now - timedelta(hours=1)
    ]
    
    if len(recent_attempts) >= 3:
        return {
            "success": False,
            "error": "Слишком много попыток",
            "message": "Превышен лимит запросов кодов. Попробуйте через час."
        }
    
    # Генерируем код
    code = generate_verification_code()
    expires = now + timedelta(minutes=5)  # Код действует 5 минут
    
    # Сохраняем код
    verification_codes[telegram_id] = {
        "code": code,
        "expires": expires,
        "attempts": 0,
        "created": now,
        "employee_name": employee.full_name
    }
    
    # Формируем сообщение
    message = f"""🔐 <b>Код входа в систему мониторинга</b>

Ваш код подтверждения: <code>{code}</code>

⏰ Код действует 5 минут
🛡️ Никому не сообщайте этот код
💻 Используйте его для входа на сайте

<i>Если вы не запрашивали код - проигнорируйте это сообщение</i>"""
    
    # Отправляем код в Telegram
    sent = await send_telegram_message(telegram_id, message)
    
    if not sent:
        # Удаляем код если не удалось отправить
        verification_codes.pop(telegram_id, None)
        return {
            "success": False,
            "error": "Ошибка отправки",
            "message": "Не удалось отправить код в Telegram. Проверьте, что бот не заблокирован."
        }
    
    logger.info(f"Код отправлен пользователю {employee.full_name} (ID: {telegram_id})")
    
    return {
        "success": True,
        "message": "Код отправлен в ваш Telegram",
        "expires_in": 300  # 5 минут в секундах
    }


@router.post("/verify-code")
async def verify_code_and_login(
    request: VerifyCodeRequest,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    """Проверяет код и авторизует пользователя"""
    
    # Очищаем истекшие коды
    cleanup_expired_codes()
    
    telegram_id = request.telegram_id
    entered_code = request.code.strip()
    
    # Проверяем наличие кода
    if telegram_id not in verification_codes:
        return {
            "success": False,
            "error": "Код не найден",
            "message": "Код не был запрошен или уже истек. Запросите новый код."
        }
    
    stored_data = verification_codes[telegram_id]
    
    # Проверяем количество попыток
    if stored_data["attempts"] >= 3:
        del verification_codes[telegram_id]
        return {
            "success": False,
            "error": "Превышен лимит попыток",
            "message": "Слишком много неверных попыток. Запросите новый код."
        }
    
    # Увеличиваем счетчик попыток
    stored_data["attempts"] += 1
    
    # Проверяем код
    if stored_data["code"] != entered_code:
        return {
            "success": False,
            "error": "Неверный код",
            "message": f"Код не совпадает. Осталось попыток: {3 - stored_data['attempts']}"
        }
    
    # Код верный - удаляем его
    del verification_codes[telegram_id]
    
    # Получаем пользователя из базы
    result = await db.execute(
        select(Employee).where(Employee.telegram_id == telegram_id)
    )
    employee = result.scalar_one_or_none()
    
    if not employee or not employee.is_active:
        return {
            "success": False,
            "error": "Пользователь недоступен",
            "message": "Аккаунт был деактивирован во время авторизации."
        }
    
    # Создаем JWT токен
    access_token = create_access_token(
        data={
            "sub": str(employee.telegram_id),
            "employee_id": employee.id,
            "is_admin": employee.is_admin,
            "username": employee.telegram_username or "",
            "full_name": employee.full_name
        }
    )
    
    logger.info(f"Успешная авторизация: {employee.full_name} (ID: {telegram_id})")
    
    # Устанавливаем cookie с токеном
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=1800,  # 30 минут
        samesite="lax",  # Изменено с "strict" для лучшей совместимости
        secure=False,    # Для localhost
        path="/",        # Доступен для всего сайта
        domain=None      # Работает для любого домена (localhost или 0.0.0.0)
    )
    
    logger.info(f"Cookie установлен для пользователя {employee.full_name}")
    
    # Отправляем уведомление об успешном входе
    success_message = f"""✅ <b>Успешный вход в систему</b>

Добро пожаловать, {employee.full_name}!

🕐 Время входа: {datetime.now().strftime('%d.%m.%Y %H:%M')}
🛡️ Сессия действует 30 минут

Вы перенаправлены в {'админ-панель' if employee.is_admin else 'личный кабинет'}."""
    
    await send_telegram_message(telegram_id, success_message)
    
    # Возвращаем JSON с информацией о redirect
    return {
        "success": True,
        "user": {
            "id": employee.telegram_id,
            "username": employee.telegram_username,
            "full_name": employee.full_name,
            "is_admin": employee.is_admin
        },
        "redirect": "/admin" if employee.is_admin else "/dashboard"
    }


@router.get("/logout")
async def logout(response: Response):
    """Выход из системы"""
    response.delete_cookie("access_token")
    return RedirectResponse(url="/login", status_code=302)


@router.get("/auth-status")
async def auth_status(current_user: dict = Depends(get_current_user)):
    """Проверка статуса авторизации"""
    return {
        "authenticated": True,
        "user": current_user
    }


@router.get("/verification-stats")
async def verification_stats():
    """Статистика активных кодов (только для отладки)"""
    cleanup_expired_codes()
    return {
        "active_codes": len(verification_codes),
        "codes": {
            str(k): {
                "expires": v["expires"].isoformat(),
                "attempts": v["attempts"],
                "employee": v["employee_name"]
            } for k, v in verification_codes.items()
        }
    }


@router.get("/debug-auth")
async def debug_auth(request: Request):
    """Отладка авторизации и cookies"""
    cookies = dict(request.cookies)
    headers = dict(request.headers)
    
    try:
        current_user = await get_current_user(request)
        auth_status = "Авторизован"
        user_info = current_user
    except Exception as e:
        auth_status = f"Ошибка авторизации: {str(e)}"
        user_info = None
    
    return {
        "auth_status": auth_status,
        "user_info": user_info,
        "cookies": cookies,
        "has_access_token": "access_token" in cookies,
        "user_agent": headers.get("user-agent"),
        "host": headers.get("host")
    } 