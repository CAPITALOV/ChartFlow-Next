"""
StockForecast / ChartFlow V2 Engine
Бэкенд на Python (FastAPI) без использования PHP.
Обеспечивает асинхронный генератор прогнозов и математические расчеты котировок.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import numpy as np
import math
from datetime import datetime, timedelta

# Создаем экземпляр приложения FastAPI
app = FastAPI(
    title="ChartFlow Forecast Engine API",
    description="Высокопроизводительный сервер математических прогнозов финансового рынка",
    version="2.5.0"
)

# Разрешаем CORS (Запросы с твоего веб-интерфейса)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # На продакшене укажи конкретный домен, например https://chartflow.ru
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Базовые цены активов для симуляции расчета
BASE_PRICES = {
    "SBER": 312.40,
    "GAZP": 168.10,
    "LKOH": 6950.00,
    "YNDX": 4120.00,
    "BTCUSD": 67450.00
}

# --- Pydantic Схемы данных (Request / Response) ---

class ForecastRequest(BaseModel):
    ticker: str = Field(..., example="SBER", description="Тикер финансового актива")
    horizon_days: int = Field(default=14, ge=3, le=90, description="Горизонт прогнозирования в днях")
    algorithm: str = Field(default="ensemble", description="Используемая алгоритмическая модель")
    volatility_level: Optional[str] = Field(default="Medium", description="Уровень волатильности (Low, Medium, High)")

class PricePoint(BaseModel):
    date: str
    price: float

class ForecastResponse(BaseModel):
    ticker: str
    current_price: float
    target_price: float
    predicted_change_percent: float
    accuracy_mape: float
    history: List[PricePoint]
    forecast: List[PricePoint]
    confidence_upper: List[PricePoint]
    confidence_lower: List[PricePoint]


# --- Алгоритмы и вспомогательные функции ---

def generate_stock_series(ticker: str, horizon: int, vol_level: str):
    """
    Математический алгоритм расчета трендов и доверительных интервалов.
    В реальном продакшене сюда подключаются библиотеки yfinance, pandas, prophet или statsmodels.
    """
    base_price = BASE_PRICES.get(ticker.upper(), 300.0)
    
    # Коэффициент волатильности
    vol_map = {"Low": 0.008, "Medium": 0.015, "High": 0.03}
    vol = vol_map.get(vol_level, 0.015)

    today = datetime.now()
    history_days = 30

    # 1. Генерация исторических данных (прошлые 30 дней)
    history_points = []
    curr_p = base_price * 0.88
    np.random.seed(len(ticker) + 42) # Фиксируем сид для стабильности тикера
    
    for i in range(history_days, 0, -1):
        date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        noise = float(np.random.normal(0, base_price * vol))
        curr_p = max(1.0, curr_p + (base_price * 0.002) + noise)
        history_points.append(PricePoint(date=date_str, price=round(curr_p, 2)))

    # Устанавливаем последнюю точку равной текущей базовой цене
    history_points[-1].price = round(base_price, 2)
    start_forecast_price = base_price

    # 2. Генерация прогнозной линии и доверительных интервалов (будущее)
    forecast_points = []
    upper_band = []
    lower_band = []

    last_val = start_forecast_price

    for i in range(1, horizon + 1):
        date_str = (today + timedelta(days=i)).strftime("%Y-%m-%d")
        
        # Легкий восходящий тренд с добавлением синусоидального волнения рынка
        trend = base_price * 0.003
        wave = math.sin(i / 2.0) * (base_price * 0.005)
        noise = float(np.random.normal(0, base_price * vol))
        
        last_val = max(1.0, last_val + trend + wave + noise)
        
        # Расширение доверительного интервала 95% во времени (закон конического распределения)
        spread = (base_price * vol * 1.6) * math.sqrt(i)
        
        forecast_points.append(PricePoint(date=date_str, price=round(last_val, 2)))
        upper_band.append(PricePoint(date=date_str, price=round(last_val + spread, 2)))
        lower_band.append(PricePoint(date=date_str, price=round(max(0.0, last_val - spread), 2)))

    # Расчет процента изменения
    target_price = forecast_points[-1].price
    pct_change = round(((target_price - start_forecast_price) / start_forecast_price) * 100, 2)
    
    # Имитация точности модели (MAPE)
    accuracy = round(100.0 - (vol * 350.0), 1)

    return {
        "ticker": ticker.upper(),
        "current_price": round(start_forecast_price, 2),
        "target_price": round(target_price, 2),
        "predicted_change_percent": pct_change,
        "accuracy_mape": accuracy,
        "history": history_points,
        "forecast": forecast_points,
        "confidence_upper": upper_band,
        "confidence_lower": lower_band
    }


# --- Эндпоинты (API Routes) ---

@app.get("/")
def read_root():
    """Тестовый роут проверки работы бэкенда"""
    return {
        "status": "online",
        "system": "ChartFlow Python FastAPI Core",
        "version": "2.5.0",
        "docs_url": "/docs"
    }


@app.post("/api/v1/forecast", response_model=ForecastResponse)
def calculate_forecast(payload: ForecastRequest):
    """
    Основной роут расчета прогноза котировок активов.
    Принимает JSON с тикером, горизонтом и моделью.
    """
    try:
        result = generate_stock_series(
            ticker=payload.ticker,
            horizon=payload.horizon_days,
            vol_level=payload.volatility_level or "Medium"
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка расчета модели: {str(e)}")


@app.get("/api/v1/tickers")
def get_available_tickers():
    """Получить список поддерживаемых тикеров"""
    return {
        "available_tickers": list(BASE_PRICES.keys())
    }


# Точка входа для локального запуска скрипта напрямую
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)