from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Float, Text, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class Employee(Base):
    __tablename__ = "employees"
    
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    telegram_username = Column(String, nullable=True)
    full_name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships with explicit foreign_keys
    messages = relationship("Message", foreign_keys="Message.employee_id", back_populates="employee")
    addressed_messages = relationship("Message", foreign_keys="Message.addressed_to_employee_id", back_populates="addressed_to")
    statistics = relationship("EmployeeStatistics", back_populates="employee")
    notifications = relationship("Notification", back_populates="employee")
    chat_memberships = relationship("ChatEmployee", back_populates="employee")


class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)  # Кто должен ответить
    chat_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, nullable=False)
    client_telegram_id = Column(BigInteger, nullable=True)  # Telegram ID клиента
    client_username = Column(String, nullable=True)
    client_name = Column(String, nullable=True)
    message_text = Column(Text, nullable=True)
    received_at = Column(DateTime, nullable=False)
    responded_at = Column(DateTime, nullable=True)
    response_time_minutes = Column(Float, nullable=True)
    is_missed = Column(Boolean, default=False)
    
    # Новые поля для умной логики
    addressed_to_employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)  # Конкретный адресат
    is_addressed_to_specific = Column(Boolean, default=False)  # Адресовано конкретно
    reply_to_message_id = Column(BigInteger, nullable=True)  # ID сообщения, на которое отвечают
    message_type = Column(String, default="client")  # 'client' или 'employee_response'
    
    # Relationships with explicit foreign_keys
    employee = relationship("Employee", foreign_keys=[employee_id], back_populates="messages")
    addressed_to = relationship("Employee", foreign_keys=[addressed_to_employee_id], back_populates="addressed_messages")


class ChatEmployee(Base):
    """Связь сотрудников с чатами для определения кому слать уведомления"""
    __tablename__ = "chat_employees"
    
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(BigInteger, nullable=False)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    is_active_in_chat = Column(Boolean, default=True)  # Активен ли в этом чате
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    employee = relationship("Employee", back_populates="chat_memberships")


class EmployeeStatistics(Base):
    __tablename__ = "employee_statistics"
    
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    date = Column(DateTime, nullable=False)
    period_type = Column(String, nullable=False)  # 'daily', 'weekly', 'monthly'
    total_messages = Column(Integer, default=0)
    responded_messages = Column(Integer, default=0)
    missed_messages = Column(Integer, default=0)
    avg_response_time = Column(Float, nullable=True)
    exceeded_15_min = Column(Integer, default=0)
    exceeded_30_min = Column(Integer, default=0)
    exceeded_60_min = Column(Integer, default=0)
    
    # Relationships
    employee = relationship("Employee", back_populates="statistics")


class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    notification_type = Column(String, nullable=False)  # 'warning_15', 'warning_30', 'warning_60'
    message_id = Column(Integer, ForeignKey("messages.id"))
    sent_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    employee = relationship("Employee", back_populates="notifications")


class SystemSettings(Base):
    __tablename__ = "system_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(String, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow) 