from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config.config import settings
from database.database import get_db
from database.models import Employee

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Создание JWT токена"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


def verify_token(token: str):
    """Проверка JWT токена"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except JWTError:
        return None


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Получение текущего пользователя из токена в cookies"""
    
    # Получаем токен из cookies
    token_cookie = request.cookies.get("access_token")
    if not token_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Убираем префикс "Bearer " если есть
    token = token_cookie
    if token.startswith("Bearer "):
        token = token[7:]
    
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный токен",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    telegram_id = payload.get("sub")
    if not telegram_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный токен",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Возвращаем информацию о пользователе из токена
    return {
        "telegram_id": int(telegram_id),
        "employee_id": payload.get("employee_id"),
        "telegram_username": payload.get("telegram_username", ""),
        "full_name": payload.get("full_name", ""),
        "is_active": payload.get("is_active", True),
        "is_admin": payload.get("is_admin", False),
        "created_at": None,  # Эти поля не храним в токене
        "last_activity": None
    }


async def get_current_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Проверка прав администратора"""
    if not current_user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав"
        )
    return current_user


async def authenticate_telegram_user(telegram_id: int, db: AsyncSession) -> Optional[Employee]:
    """Аутентификация пользователя по Telegram ID"""
    result = await db.execute(
        select(Employee).where(Employee.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        return None
    
    # Администраторы всегда могут войти
    if user.is_admin:
        return user
    
    # Обычные сотрудники только если активны
    if user.is_active:
        return user
    
    return None


def create_telegram_auth_url(bot_username: str, auth_url: str) -> str:
    """Создание URL для авторизации через Telegram"""
    return f"https://t.me/{bot_username}?start=auth_{auth_url}" 