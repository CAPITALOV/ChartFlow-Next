#!/usr/bin/env python3
"""
Walk-forward backtest моделей прогнозирования.

Метод: для каждой модели обучаемся на первых N точках истории,
прогнозируем следующие `horizon` дней, сравниваем с фактом,
сдвигаем окно на `step` дней и повторяем.

Использование:
    .venv/bin/python backtest.py SBER
    .venv/bin/python backtest.py SBER --horizon 14 --step 7 --min-train 120
    .venv/bin/python backtest.py SBER --save     # записать в БД как completed
    .venv/bin/python backtest.py SBER GAZP LKOH  # несколько тикеров

Вывод: таблица с MAPE/MAE/RMSE по каждой модели.
"""
import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from db import SessionLocal, PriceHistory, ForecastRun, ForecastPoint
from forecaster import MODELS, HAS_STATSMODELS, run_forecast
from moex_client import fetch_history


logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
log = logging.getLogger("backtest")


def load_history(db, ticker: str, days: int = 730) -> pd.DataFrame:
    """История из БД, при нехватке — догружаем с MOEX."""
    ticker = ticker.upper()
    since = date.today() - timedelta(days=days)
    rows = (
        db.query(PriceHistory)
        .filter(PriceHistory.ticker == ticker, PriceHistory.date >= since)
        .order_by(PriceHistory.date)
        .all()
    )
    if len(rows) < 200:
        log.info(f"{ticker}: в БД {len(rows)} точек, догружаю с MOEX...")
        try:
            for h in fetch_history(ticker, since, date.today()):
                if not db.query(PriceHistory).filter_by(ticker=ticker, date=h["date"]).first():
                    db.add(PriceHistory(ticker=ticker, **h))
            db.commit()
        except Exception as e:
            log.error(f"{ticker}: MOEX недоступен — {e}")
        rows = (
            db.query(PriceHistory)
            .filter(PriceHistory.ticker == ticker, PriceHistory.date >= since)
            .order_by(PriceHistory.date)
            .all()
        )
    return pd.DataFrame([{"date": r.date, "close": r.close} for r in rows])


def walk_forward(df: pd.DataFrame, model_name: str, horizon: int, step: int,
                 min_train: int) -> pd.DataFrame:
    """Скользящее окно. Возвращает DataFrame с точками прогноз/факт/ошибка."""
    results = []
    n = len(df)
    i = min_train
    windows = 0
    while i + horizon <= n:
        train = df.iloc[:i].copy()
        actual = df.iloc[i:i + horizon].copy()
        try:
            res = run_forecast("BT", train, model_name, horizon)
            preds = res["predictions"]
        except Exception as e:
            log.warning(f"window {i}/{n}: {e}")
            i += step
            continue
        windows += 1
        for pred, (_, row) in zip(preds, actual.iterrows()):
            close = float(row["close"])
            if close <= 0:
                continue
            ae = abs(pred - close)
            results.append({
                "target_date": row["date"],
                "predicted": float(pred),
                "actual": close,
                "abs_error": ae,
                "ape": ae / close,
            })
        i += step
    if windows == 0:
        return pd.DataFrame()
    return pd.DataFrame(results)


def compute_metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0, "mape": None, "mae": None, "rmse": None}
    return {
        "n": len(df),
        "mape": float(df["ape"].mean() * 100),
        "mae": float(df["abs_error"].mean()),
        "rmse": float((df["abs_error"] ** 2).mean() ** 0.5),
    }


def save_as_completed(db, ticker: str, model_name: str, metrics: dict,
                      points: pd.DataFrame, horizon: int, last_hist: pd.DataFrame):
    """Записывает backtest как завершённый ForecastRun, чтобы попал в /api/v1/stats."""
    run = ForecastRun(
        ticker=ticker,
        model=model_name,
        horizon_days=horizon,
        last_hist_date=last_hist["date"].iloc[-1],
        last_hist_price=float(last_hist["close"].iloc[-1]),
        target_price=float(points["predicted"].iloc[-1]) if len(points) else None,
        predicted_change_percent=None,
        status="completed",
        mape_avg=metrics["mape"],
        mae_avg=metrics["mae"],
        rmse_avg=metrics["rmse"],
    )
    db.add(run)
    db.flush()
    for _, p in points.iterrows():
        db.add(ForecastPoint(
            run_id=run.id,
            target_date=p["target_date"],
            predicted_price=float(p["predicted"]),
            actual_price=float(p["actual"]),
            abs_error=float(p["abs_error"]),
            ape=float(p["ape"]),
            verified=True,
        ))
    db.commit()
    return run.id


def fmt(x, digits=2):
    if x is None:
        return "—"
    return f"{x:.{digits}f}"


def run_ticker(db, ticker: str, args) -> dict:
    df = load_history(db, ticker, args.days)
    if len(df) < args.min_train + args.horizon + 10:
        print(f"  ✗ {ticker}: истории {len(df)} точек, нужно ≥ "
              f"{args.min_train + args.horizon + 10}. Пропускаю.")
        return {}

    print(f"\n{'═' * 70}")
    print(f"  {ticker}: {len(df)} точек истории, "
          f"диапазон {df['date'].iloc[0]} .. {df['date'].iloc[-1]}")
    print(f"  walk-forward: min_train={args.min_train}, "
          f"horizon={args.horizon}, step={args.step}")
    print(f"{'═' * 70}")

    print(f"\n  {'Модель':<14} {'Точек':>7} {'MAPE %':>10} "
          f"{'MAE ₽':>10} {'RMSE ₽':>10}  Оценка")
    print(f"  {'─' * 62}")

    summary = {}
    best_model, best_mape = None, float("inf")

    for model_name in MODELS:
        pts = walk_forward(df, model_name, args.horizon, args.step, args.min_train)
        m = compute_metrics(pts)
        summary[model_name] = m

        if m["n"] == 0:
            print(f"  {model_name:<14} {'—':>7} {'—':>10} {'—':>10} {'—':>10}  пропуск")
            continue

        rating = (
            "🟢 отлично" if m["mape"] < 3
            else "🟡 хорошо" if m["mape"] < 6
            else "🟠 слабо"   if m["mape"] < 12
            else "🔴 плохо"
        )
        print(f"  {model_name:<14} {m['n']:>7} {m['mape']:>10.2f} "
              f"{m['mae']:>10.2f} {m['rmse']:>10.2f}  {rating}")

        if m["mape"] < best_mape:
            best_mape = m["mape"]
            best_model = model_name

        if args.save:
            rid = save_as_completed(db, ticker, model_name, m, pts,
                                    args.horizon, df)
            print(f"                 ↳ записан в БД как run_id={rid}")

    if best_model:
        print(f"\n  🏆 Лучшая модель на {ticker}: "
              f"{best_model} (MAPE={best_mape:.2f}%)")

    return summary


def main():
    ap = argparse.ArgumentParser(description="Walk-forward backtest моделей ChartFlow")
    ap.add_argument("tickers", nargs="+", help="Тикеры (SBER GAZP LKOH ...)")
    ap.add_argument("--horizon", type=int, default=14, help="Горизонт прогноза (дни)")
    ap.add_argument("--step", type=int, default=7, help="Шаг сдвига окна (дни)")
    ap.add_argument("--min-train", type=int, default=120, help="Минимум точек для обучения")
    ap.add_argument("--days", type=int, default=730, help="Сколько дней истории брать")
    ap.add_argument("--save", action="store_true",
                    help="Сохранить результаты в БД (появятся в /api/v1/stats)")
    args = ap.parse_args()

    if not HAS_STATSMODELS:
        print("⚠  statsmodels не установлен — доступны только naive/moving_avg")

    db = SessionLocal()
    try:
        all_summary = {}
        for t in args.tickers:
            all_summary[t.upper()] = run_ticker(db, t.upper(), args)

        # Итоговая сводка по всем тикерам
        if len(args.tickers) > 1:
            print(f"\n{'═' * 70}")
            print(f"  СВОДКА")
            print(f"{'═' * 70}")
            for t, summ in all_summary.items():
                if not summ:
                    continue
                valid = {m: v for m, v in summ.items() if v["n"] > 0}
                if not valid:
                    continue
                best = min(valid, key=lambda m: valid[m]["mape"])
                print(f"  {t:<8} лучшая: {best:<14} MAPE={valid[best]['mape']:.2f}%")
        print()
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main() or 0)