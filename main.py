"""
ChartFlow / StockForecast V3 — FastAPI backend.
Реальные модели прогноза, верификация, авторизация, админка.
"""
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from admin import setup_admin
from auth import (
    create_access_token, get_current_user, hash_password,
    require_user, verify_password,
)
from config import settings
from db import (
    Base, engine, get_db, ForecastPoint, ForecastRun,
    PriceHistory, User, WatchlistItem,
)
from forecaster import HAS_STATSMODELS, MODELS, run_forecast
from moex_client import available_tickers, fetch_current_price, fetch_history, is_crypto
from scheduler import start_scheduler, stop_scheduler
from verifier import verify_pending_points

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    start_scheduler()
    log.info("App started")
    yield
    stop_scheduler()


app = FastAPI(
    title="ChartFlow Forecast Engine API",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Pydantic ----------

class RegisterIn(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6)
    email: Optional[str] = None


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    email: Optional[str]
    role: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ForecastIn(BaseModel):
    ticker: str
    horizon_days: int = Field(default=14, ge=3, le=90)
    algorithm: str = Field(default="holt_winters")
    model: Optional[str] = None  # алиас для algorithm


class PricePoint(BaseModel):
    date: str
    price: float


class ForecastOut(BaseModel):
    run_id: int
    ticker: str
    model: str
    current_price: float
    target_price: float
    predicted_change_percent: float
    accuracy_mape: Optional[float]
    accuracy_mape_label: str
    source: str
    history: list[PricePoint]
    forecast: list[PricePoint]
    confidence_upper: list[PricePoint]
    confidence_lower: list[PricePoint]


class RunOut(BaseModel):
    run_id: int
    ticker: str
    model: str
    horizon_days: int
    created_at: str
    status: str
    target_price: Optional[float]
    predicted_change_percent: Optional[float]
    mape: Optional[float]
    mae: Optional[float]
    rmse: Optional[float]


# ---------- Startup seeding ----------

@app.on_event("startup")
def seed_admin():
    db = next(get_db())
    try:
        if not db.query(User).filter(User.username == settings.admin_user).first():
            db.add(User(
                username=settings.admin_user,
                email=f"{settings.admin_user}@chartflow.local",
                password_hash=hash_password(settings.admin_password),
                role="admin",
            ))
            db.commit()
            log.info(f"Seeded admin user '{settings.admin_user}'")
    finally:
        db.close()


# ---------- Health ----------

@app.get("/")
def root():
    return {
        "status": "online",
        "system": "ChartFlow FastAPI Core",
        "version": "3.0.0",
        "statsmodels": HAS_STATSMODELS,
        "models": list(MODELS.keys()),
    }


@app.get("/api/v1/models")
def list_models():
    return {"models": list(MODELS.keys()), "statsmodels": HAS_STATSMODELS}


@app.get("/api/v1/tickers")
def list_tickers():
    return {"tickers": available_tickers()}


@app.get("/api/v1/price/{ticker}")
def current_price(ticker: str):
    p = fetch_current_price(ticker.upper())
    return {"ticker": ticker.upper(), "price": p, "source": "crypto" if is_crypto(ticker) else "moex"}


# ---------- Auth ----------

@app.post("/api/v1/auth/register", response_model=UserOut)
def register(req: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(400, "Пользователь уже существует")
    u = User(
        username=req.username,
        email=req.email,
        password_hash=hash_password(req.password),
        role="user",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return UserOut(id=u.id, username=u.username, email=u.email, role=u.role)


@app.post("/api/v1/auth/login", response_model=TokenOut)
def login(req: LoginIn, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.username == req.username).first()
    if not u or not verify_password(req.password, u.password_hash) or not u.is_active:
        raise HTTPException(401, "Неверный логин или пароль")
    return TokenOut(
        access_token=create_access_token(u),
        user=UserOut(id=u.id, username=u.username, email=u.email, role=u.role),
    )


@app.get("/api/v1/auth/me", response_model=UserOut)
def me(user: User = Depends(require_user)):
    return UserOut(id=user.id, username=user.username, email=user.email, role=user.role)


# ---------- History loading ----------

def _load_history(db: Session, ticker: str, days: int) -> pd.DataFrame:
    ticker = ticker.upper()
    since = date.today() - timedelta(days=days)
    rows = (
        db.query(PriceHistory)
        .filter(PriceHistory.ticker == ticker, PriceHistory.date >= since)
        .order_by(PriceHistory.date)
        .all()
    )
    if len(rows) < settings.min_history_points:
        try:
            fetched = fetch_history(ticker, since, date.today())
        except Exception as e:
            raise HTTPException(502, f"Ошибка загрузки истории: {e}")
        for h in fetched:
            if not db.query(PriceHistory).filter_by(ticker=ticker, date=h["date"]).first():
                db.add(PriceHistory(ticker=ticker, **h))
        db.commit()
        rows = (
            db.query(PriceHistory)
            .filter(PriceHistory.ticker == ticker, PriceHistory.date >= since)
            .order_by(PriceHistory.date)
            .all()
        )
    if not rows:
        return pd.DataFrame(columns=["date", "close"])
    return pd.DataFrame([{"date": r.date, "close": r.close} for r in rows])


@app.post("/api/v1/backfill/{ticker}")
def backfill(ticker: str, days: int = Query(730, ge=90, le=3650), db: Session = Depends(get_db)):
    since = date.today() - timedelta(days=days)
    try:
        fetched = fetch_history(ticker.upper(), since, date.today())
    except Exception as e:
        raise HTTPException(502, f"MOEX/Binance error: {e}")
    inserted = 0
    for h in fetched:
        if not db.query(PriceHistory).filter_by(ticker=ticker.upper(), date=h["date"]).first():
            db.add(PriceHistory(ticker=ticker.upper(), **h))
            inserted += 1
    db.commit()
    return {"ticker": ticker.upper(), "fetched": len(fetched), "inserted": inserted}


# ---------- Forecast ----------

@app.post("/api/v1/forecast", response_model=ForecastOut)
def forecast(
    req: ForecastIn,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user),
):
    ticker = req.ticker.upper()
    model = (req.model or req.algorithm or "holt_winters").lower()
    if model not in MODELS:
        raise HTTPException(400, f"Модель не найдена: {model}. Доступно: {list(MODELS)}")

    hist = _load_history(db, ticker, settings.default_history_days)
    if len(hist) < settings.min_history_points:
        raise HTTPException(400, f"Недостаточно истории ({len(hist)} точек)")

    try:
        result = run_forecast(ticker, hist, model, req.horizon_days)
    except ValueError as e:
        raise HTTPException(400, str(e))

    last_close = result["last_price"]
    target = result["predictions"][-1]
    pct = round((target - last_close) / last_close * 100, 2) if last_close else 0.0

    run = ForecastRun(
        ticker=ticker,
        model=model,
        horizon_days=req.horizon_days,
        last_hist_date=result["last_date"],
        last_hist_price=last_close,
        target_price=target,
        predicted_change_percent=pct,
        status="active",
        user_id=user.id if user else None,
    )
    db.add(run)
    db.flush()
    for d, p in zip(result["target_dates"], result["predictions"]):
        db.add(ForecastPoint(run_id=run.id, target_date=d, predicted_price=p))
    db.commit()

    history = [
        PricePoint(date=r.date.isoformat(), price=round(r.close, 2))
        for r in (db.query(PriceHistory)
                    .filter(PriceHistory.ticker == ticker)
                    .order_by(PriceHistory.date.desc()).limit(30).all()[::-1])
    ]
    std = float(hist["close"].pct_change().std() or 0.02)
    fpts, up, lo = [], [], []
    for i, (d, p) in enumerate(zip(result["target_dates"], result["predictions"]), 1):
        spread = p * std * 1.96 * (i ** 0.5)
        fpts.append(PricePoint(date=d.isoformat(), price=round(p, 2)))
        up.append(PricePoint(date=d.isoformat(), price=round(p + spread, 2)))
        lo.append(PricePoint(date=d.isoformat(), price=round(max(0, p - spread), 2)))

    completed = (
        db.query(ForecastRun)
        .filter(
            ForecastRun.ticker == ticker,
            ForecastRun.model == model,
            ForecastRun.status == "completed",
            ForecastRun.mape_avg.isnot(None),
        )
        .all()
    )
    mape = round(sum(r.mape_avg for r in completed) / len(completed), 2) if completed else None

    return ForecastOut(
        run_id=run.id,
        ticker=ticker,
        model=model,
        current_price=round(last_close, 2),
        target_price=round(target, 2),
        predicted_change_percent=pct,
        accuracy_mape=mape,
        accuracy_mape_label=(
            f"{mape}% (по {len(completed)} завершённым прогнозам)"
            if mape is not None else "Собираем статистику..."
        ),
        source=("Binance" if is_crypto(ticker) else "MOEX") + f" + {model}",
        history=history,
        forecast=fpts,
        confidence_upper=up,
        confidence_lower=lo,
    )


@app.get("/api/v1/runs/{ticker}", response_model=list[RunOut])
def list_runs(
    ticker: str,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ForecastRun)
        .filter(ForecastRun.ticker == ticker.upper())
        .order_by(ForecastRun.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        RunOut(
            run_id=r.id, ticker=r.ticker, model=r.model, horizon_days=r.horizon_days,
            created_at=r.created_at.isoformat() if r.created_at else "",
            status=r.status, target_price=r.target_price,
            predicted_change_percent=r.predicted_change_percent,
            mape=r.mape_avg, mae=r.mae_avg, rmse=r.rmse_avg,
        )
        for r in rows
    ]


@app.get("/api/v1/stats/{ticker}")
def stats(ticker: str, db: Session = Depends(get_db)):
    runs = (
        db.query(ForecastRun)
        .filter(ForecastRun.ticker == ticker.upper(), ForecastRun.status == "completed")
        .all()
    )
    by_model: dict[str, list[ForecastRun]] = {}
    for r in runs:
        by_model.setdefault(r.model, []).append(r)

    out = {}
    for model, rs in by_model.items():
        mapes = [r.mape_avg for r in rs if r.mape_avg is not None]
        maes = [r.mae_avg for r in rs if r.mae_avg is not None]
        out[model] = {
            "completed_runs": len(rs),
            "mape_avg": round(sum(mapes) / len(mapes), 2) if mapes else None,
            "mape_best": round(min(mapes), 2) if mapes else None,
            "mae_avg": round(sum(maes) / len(maes), 4) if maes else None,
        }
    return {"ticker": ticker.upper(), "models": out}


@app.post("/api/v1/verify-now")
def verify_now(db: Session = Depends(get_db)):
    n = verify_pending_points(db)
    return {"verified_points": n}


# ---------- Watchlist ----------

@app.get("/api/v1/watchlist")
def get_watchlist(db: Session = Depends(get_db), user: User = Depends(require_user)):
    items = db.query(WatchlistItem).filter(WatchlistItem.user_id == user.id).all()
    return {"tickers": [i.ticker for i in items]}


@app.post("/api/v1/watchlist/{ticker}")
def add_watch(ticker: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    t = ticker.upper()
    if not db.query(WatchlistItem).filter_by(user_id=user.id, ticker=t).first():
        db.add(WatchlistItem(user_id=user.id, ticker=t))
        db.commit()
    return {"ok": True, "ticker": t}


@app.delete("/api/v1/watchlist/{ticker}")
def rm_watch(ticker: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    item = db.query(WatchlistItem).filter_by(user_id=user.id, ticker=ticker.upper()).first()
    if item:
        db.delete(item)
        db.commit()
    return {"ok": True}


# ---------- Admin ----------

setup_admin(app, engine)


# ---------- Error handler ----------

@app.exception_handler(Exception)
async def global_handler(request, exc):
    log.exception("Unhandled exception")
    return JSONResponse(status_code=500, content={"detail": str(exc)})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)