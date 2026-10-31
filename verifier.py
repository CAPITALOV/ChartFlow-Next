import math
import logging
from datetime import date
from sqlalchemy.orm import Session
from db import ForecastRun, ForecastPoint, PriceHistory
from moex_client import fetch_history

log = logging.getLogger("verifier")


def verify_pending_points(db: Session) -> int:
    today = date.today()
    pending = (
        db.query(ForecastPoint)
        .filter(ForecastPoint.verified.is_(False), ForecastPoint.target_date <= today)
        .all()
    )
    if not pending:
        return 0

    by_ticker: dict[str, list[ForecastPoint]] = {}
    for p in pending:
        by_ticker.setdefault(p.run.ticker, []).append(p)

    verified = 0
    for ticker, points in by_ticker.items():
        dmin = min(p.target_date for p in points)
        dmax = max(p.target_date for p in points)
        try:
            hist = fetch_history(ticker, dmin, dmax)
        except Exception as e:
            log.warning(f"verify {ticker}: {e}")
            continue
        prices = {h["date"]: h["close"] for h in hist}

        for p in points:
            actual = prices.get(p.target_date)
            if actual is None:
                continue
            p.actual_price = actual
            p.verified = True
            p.abs_error = abs(p.predicted_price - actual)
            p.ape = p.abs_error / actual if actual else None
            verified += 1
            if not db.query(PriceHistory).filter_by(ticker=ticker, date=p.target_date).first():
                db.add(PriceHistory(ticker=ticker, date=p.target_date, close=actual))
        db.flush()

    _update_run_metrics(db)
    db.commit()
    log.info(f"Verified {verified} points")
    return verified


def _update_run_metrics(db: Session):
    runs = db.query(ForecastRun).filter(ForecastRun.status == "active").all()
    for run in runs:
        pts = run.points
        if not pts or not all(p.verified for p in pts):
            continue
        apes = [p.ape for p in pts if p.ape is not None]
        errs = [p.abs_error for p in pts if p.abs_error is not None]
        run.mape_avg = (sum(apes) / len(apes) * 100) if apes else None
        run.mae_avg = (sum(errs) / len(errs)) if errs else None
        run.rmse_avg = math.sqrt(sum(e * e for e in errs) / len(errs)) if errs else None
        run.status = "completed"
    db.flush()