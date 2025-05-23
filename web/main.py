from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import uvicorn

from config.config import settings
from database.database import init_db
from .routers import auth, employees, statistics, dashboard
from .routes import settings as settings_router
from .auth import get_current_user

app = FastAPI(title="Employee Activity Tracker", version="1.0.0")

# CORS настройки
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключение статических файлов
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# Шаблоны
templates = Jinja2Templates(directory="web/templates")

# Подключение роутеров
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(employees.router, prefix="/api/employees", tags=["employees"])
app.include_router(statistics.router, prefix="/api/statistics", tags=["statistics"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(settings_router.router)  # Настройки системы


@app.on_event("startup")
async def startup_event():
    """Инициализация при запуске"""
    await init_db()


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Главная страница"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Страница входа"""
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Главная панель управления"""
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/employees", response_class=HTMLResponse)
async def employees_page(request: Request):
    """Страница управления сотрудниками"""
    return templates.TemplateResponse("employees.html", {"request": request})


@app.get("/statistics", response_class=HTMLResponse)
async def statistics_page(request: Request):
    """Страница статистики"""
    return templates.TemplateResponse("statistics.html", {"request": request})


@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    """Личный кабинет сотрудника"""
    return templates.TemplateResponse("profile.html", {"request": request})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Страница настроек системы (только для админов)"""
    return templates.TemplateResponse("settings.html", {"request": request})


@app.get("/health")
async def health_check():
    """Проверка работоспособности"""
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(
        "web.main:app",
        host=settings.web_host,
        port=settings.web_port,
        reload=True
    ) 