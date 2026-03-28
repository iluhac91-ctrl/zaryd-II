from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String, unique=True, index=True, nullable=False)
    pin_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    rentals = relationship("Rental", back_populates="user")


class Slot(Base):
    __tablename__ = "slots"

    id = Column(Integer, primary_key=True, index=True)
    slot_number = Column(Integer, unique=True, nullable=False)
    relay_channel = Column(Integer, nullable=False)
    status = Column(String, default="available")  
    # available = слот со свободным powerbank
    # empty = пустой слот для возврата
    # rented = powerbank выдан
    # fault = ошибка


class Rental(Base):
    __tablename__ = "rentals"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    slot_number = Column(Integer, nullable=False)
    status = Column(String, default="active")  
    # active / returned

    start_time = Column(DateTime(timezone=True), server_default=func.now())
    end_time = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="rentals")