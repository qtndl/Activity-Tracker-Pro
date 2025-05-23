from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
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
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> Employee:
    """Получение текущего пользователя из токена"""
    token = credentials.credentials
    
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный токен",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный токен",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    result = await db.execute(
        select(Employee).where(Employee.id == int(user_id))
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    
    # Администраторы всегда могут войти в систему, даже если деактивированы
    # Деактивация для админов означает только отключение уведомлений бота
    if not user.is_active and not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ваш аккаунт временно деактивирован. Обратитесь к администратору."
        )
    
    return user


async def get_current_admin(current_user: Employee = Depends(get_current_user)) -> Employee:
    """Проверка прав администратора"""
    if not current_user.is_admin:
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