from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Float, Text, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class Employee(Base):
    __tablename__ = "employees"
    
    id = Column(BigInteger, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
    telegram_username = Column(String, nullable=True)
    full_name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    messages = relationship("Message", back_populates="employee", foreign_keys="Message.employee_id")


class Message(Base):
    __tablename__ = "messages"
    
    id = Column(BigInteger, primary_key=True, index=True)
    employee_id = Column(BigInteger, ForeignKey("employees.id"))
    chat_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, nullable=False)
    client_telegram_id = Column(BigInteger, nullable=True)
    client_username = Column(String, nullable=True)
    client_name = Column(String, nullable=True)
    message_text = Column(Text, nullable=True)
    message_type = Column(String, default="client")  # client, employee
    addressed_to_employee_id = Column(BigInteger, nullable=True)
    is_addressed_to_specific = Column(Boolean, default=False)
    received_at = Column(DateTime, default=datetime.utcnow)
    responded_at = Column(DateTime, nullable=True)
    response_time_minutes = Column(Float, nullable=True)
    answered_by_employee_id = Column(BigInteger, ForeignKey("employees.id"), nullable=True)
    is_missed = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)
    is_deferred = Column(Boolean, default=False)
    
    # Relationships
    employee = relationship("Employee", back_populates="messages", foreign_keys=[employee_id])
    answered_by = relationship("Employee", foreign_keys=[answered_by_employee_id])


class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(BigInteger, primary_key=True, index=True)
    message_id = Column(BigInteger, ForeignKey("messages.id"))
    employee_id = Column(BigInteger, ForeignKey("employees.id"))
    notification_type = Column(String, nullable=False)  # '15min', '30min', '60min'
    sent_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    message = relationship("Message")
    employee = relationship("Employee")


class SystemSettings(Base):
    __tablename__ = "system_settings"
    
    id = Column(BigInteger, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(String, nullable=True)
    description = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ChatEmployee(Base):
    __tablename__ = "chat_employees"
    
    id = Column(BigInteger, primary_key=True, index=True)
    chat_id = Column(BigInteger, nullable=False)
    employee_id = Column(BigInteger, ForeignKey("employees.id"))
    is_active_in_chat = Column(Boolean, default=True)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    assigned_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    employee = relationship("Employee")


class DeferredMessageSimple(Base):
    __tablename__ = "deferred_messages_simple"

    id = Column(BigInteger, primary_key=True, index=True)
    from_user_id = Column(BigInteger, nullable=True)  # теперь nullable
    from_username = Column(String, nullable=True)
    text = Column(Text, nullable=True)
    date = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    client_telegram_id = Column(BigInteger, nullable=True)
    employee_id = Column(BigInteger, ForeignKey("employees.id"), nullable=True)
    chat_id = Column(BigInteger, nullable=True)
    # Новое поле:
    original_message_id = Column(BigInteger, ForeignKey("messages.id"), nullable=True, index=True)

    # Опционально — чтобы удобно тянуть исходное сообщение:
    original_message = relationship("Message", lazy="joined")