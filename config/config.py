from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    # Telegram Bot
    bot_token: str = Field(..., env="BOT_TOKEN")
    admin_chat_id: Optional[str] = Field(None, env="ADMIN_CHAT_ID")
    
    # Database
    database_url: str = Field(..., env="DATABASE_URL")
    
    # Web App
    secret_key: str = Field(..., env="SECRET_KEY")
    algorithm: str = Field("HS256", env="ALGORITHM")
    access_token_expire_minutes: int = Field(43200, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    
    # Google Sheets
    google_sheets_enabled: bool = Field(False, env="GOOGLE_SHEETS_ENABLED")
    google_sheets_credentials_file: Optional[str] = Field(None, env="GOOGLE_SHEETS_CREDENTIALS_FILE")
    spreadsheet_id: Optional[str] = Field(None, env="SPREADSHEET_ID")
    
    # Application Settings
    response_time_warning_1: int = Field(15, env="RESPONSE_TIME_WARNING_1")
    response_time_warning_2: int = Field(30, env="RESPONSE_TIME_WARNING_2")
    response_time_warning_3: int = Field(60, env="RESPONSE_TIME_WARNING_3")
    
    # Web Server
    web_host: str = Field("0.0.0.0", env="WEB_HOST")
    web_port: int = Field(8000, env="WEB_PORT")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings() 