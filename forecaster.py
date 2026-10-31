from datetime import date, timedelta
import logging
import pandas as pd

log = logging.getLogger("forecaster")

try:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    from statsmodels.tsa.arima.model import ARIMA
    HAS_STATSMODELS = True
except Exception:
    HAS_STATSMODELS = False
    log.warning("statsmodels not available — falling back to naive/ma")


def _next_trading_days(last_date: date, n: int) -> list[date]:
    days, d = [], last_date
    while len(days) < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            days.append(d)
    return days


def _naive(s: pd.Series, h: int) -> list[float]:
    return [float(s.iloc[-1])] * h


def _moving_avg(s: pd.Series, h: int, window: int = 20) -> list[float]:
    return [float(s.tail(window).mean())] * h


def _holt_winters(s: pd.Series, h: int) -> list[float]:
    if not HAS_STATSMODELS:
        return _naive(s, h)
    try:
        m = ExponentialSmoothing(
            s.values, trend="add", seasonal=None,
            initialization_method="estimated",
        ).fit()
        return [float(x) for x in m.forecast(h)]
    except Exception as e:
        log.warning(f"holt_winters failed: {e}; using naive")
        return _naive(s, h)


def _arima(s: pd.Series, h: int) -> list[float]:
    if not HAS_STATSMODELS:
        return _naive(s, h)
    try:
        m = ARIMA(s.values, order=(2, 1, 1)).fit()
        return [float(x) for x in m.forecast(h)]
    except Exception as e:
        log.warning(f"arima failed: {e}; using naive")
        return _naive(s, h)


MODELS = {
    "naive": _naive,
    "moving_avg": _moving_avg,
    "holt_winters": _holt_winters,
    "arima": _arima,
}


def run_forecast(ticker: str, history: pd.DataFrame, model_name: str, horizon: int) -> dict:
    if model_name not in MODELS:
        raise ValueError(f"Unknown model: {model_name}")
    if len(history) < 60:
        raise ValueError(f"Not enough history ({len(history)}, need ≥60)")

    series = history.set_index("date")["close"].astype(float).sort_index()
    values = MODELS[model_name](series, horizon)

    last_date = history["date"].iloc[-1]
    last_price = float(history["close"].iloc[-1])
    target_dates = _next_trading_days(last_date, horizon)

    return {
        "ticker": ticker,
        "model": model_name,
        "last_date": last_date,
        "last_price": last_price,
        "target_dates": target_dates,
        "predictions": values,
    }