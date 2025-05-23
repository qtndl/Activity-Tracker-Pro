from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from database.database import get_db
from web.auth import create_access_token, authenticate_telegram_user

router = APIRouter()


class TelegramAuthRequest(BaseModel):
    telegram_id: int


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_info: dict


@router.post("/telegram", response_model=TokenResponse)
async def telegram_auth(
    auth_data: TelegramAuthRequest,
    db: AsyncSession = Depends(get_db)
):
    """Авторизация через Telegram ID"""
    user = await authenticate_telegram_user(auth_data.telegram_id, db)
    
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Пользователь не найден. Обратитесь к администратору для регистрации."
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="Ваш аккаунт деактивирован"
        )
    
    # Создаем токен в том же формате, что и новая система
    access_token = create_access_token(data={
        "sub": str(user.telegram_id),  # Используем telegram_id вместо id
        "employee_id": user.id,
        "telegram_id": user.telegram_id,
        "telegram_username": user.telegram_username,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "is_admin": user.is_admin
    })
    
    return TokenResponse(
        access_token=access_token,
        user_info={
            "employee_id": user.id,
            "telegram_id": user.telegram_id,
            "telegram_username": user.telegram_username,
            "full_name": user.full_name,
            "is_active": user.is_active,
            "is_admin": user.is_admin,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "updated_at": user.updated_at.isoformat() if user.updated_at else None
        }
    )


@router.get("/telegram/callback")
async def telegram_callback(
    user_id: int = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Callback для авторизации через Telegram (для веб-виджета)"""
    user = await authenticate_telegram_user(user_id, db)
    
    if not user:
        return JSONResponse(
            status_code=404,
            content={"error": "Пользователь не найден"}
        )
    
    # Создаем токен в правильном формате
    access_token = create_access_token(data={
        "sub": str(user.telegram_id),
        "employee_id": user.id,
        "telegram_id": user.telegram_id,
        "telegram_username": user.telegram_username,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "is_admin": user.is_admin
    })
    
    # Возвращаем HTML с JavaScript для сохранения токена
    html_content = f"""
    <html>
    <head>
        <title>Авторизация...</title>
    </head>
    <body>
        <script>
            localStorage.setItem('access_token', '{access_token}');
            localStorage.setItem('user_info', JSON.stringify({{
                employee_id: {user.id},
                telegram_id: {user.telegram_id},
                telegram_username: '{user.telegram_username}',
                full_name: '{user.full_name}',
                is_active: {str(user.is_active).lower()},
                is_admin: {str(user.is_admin).lower()},
                created_at: '{user.created_at.isoformat() if user.created_at else None}',
                updated_at: '{user.updated_at.isoformat() if user.updated_at else None}'
            }}));
            window.location.href = '/dashboard';
        </script>
        <p>Авторизация успешна, перенаправление...</p>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)


@router.post("/logout")
async def logout():
    """Выход из системы"""
    # На клиенте нужно просто удалить токен из localStorage
    return {"message": "Выход выполнен успешно"} 