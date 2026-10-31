from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Date, DateTime,
    Boolean, ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.sql import func
from config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(16), default="user")  # user | admin
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())


class PriceHistory(Base):
    __tablename__ = "price_history"
    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float, nullable=False)
    volume = Column(Float)
    __table_args__ = (UniqueConstraint("ticker", "date", name="uq_price_ticker_date"),)


class ForecastRun(Base):
    __tablename__ = "forecast_runs"
    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False, index=True)
    model = Column(String(32), nullable=False)
    horizon_days = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=func.now())
    last_hist_date = Column(Date)
    last_hist_price = Column(Float)
    target_price = Column(Float)
    predicted_change_percent = Column(Float)
    status = Column(String(16), default="active", index=True)  # active|completed|failed
    mape_avg = Column(Float)
    mae_avg = Column(Float)
    rmse_avg = Column(Float)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    points = relationship("ForecastPoint", back_populates="run", cascade="all, delete-orphan")


class ForecastPoint(Base):
    __tablename__ = "forecast_points"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("forecast_runs.id"), nullable=False, index=True)
    target_date = Column(Date, nullable=False, index=True)
    predicted_price = Column(Float, nullable=False)
    actual_price = Column(Float, nullable=True)
    abs_error = Column(Float, nullable=True)
    ape = Column(Float, nullable=True)
    verified = Column(Boolean, default=False, index=True)
    run = relationship("ForecastRun", back_populates="points")


class WatchlistItem(Base):
    __tablename__ = "watchlist"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    ticker = Column(String(20), nullable=False)
    added_at = Column(DateTime, default=func.now())
    __table_args__ = (UniqueConstraint("user_id", "ticker", name="uq_watch_user_ticker"),)