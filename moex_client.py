import time
import logging
from datetime import date, datetime
from typing import Optional
import httpx
from config import settings

log = logging.getLogger("moex")

MOEX_TICKERS = {"SBER", "GAZP", "LKOH", "YNDX", "ROSN", "VTBR", "GMKN", "NVTK", "TATN", "SNGS", "MTSS", "MGNT"}
CRYPTO_TICKERS = {"BTCUSD", "ETHUSD", "BTCUSDT", "ETHUSDT"}


def is_crypto(ticker: str) -> bool:
    return ticker.upper() in CRYPTO_TICKERS or ticker.upper().endswith("USDT")


def fetch_history(ticker: str, from_date: date, to_date: date) -> list[dict]:
    ticker = ticker.upper()
    if is_crypto(ticker):
        return _fetch_crypto_history(ticker, from_date, to_date)
    return _fetch_moex_history(ticker, from_date, to_date)


def _fetch_moex_history(ticker: str, from_date: date, to_date: date) -> list[dict]:
    url = (
        f"{settings.moex_base_url}/history/engines/stock/markets/shares/"
        f"boards/{settings.moex_board}/securities/{ticker}.json"
    )
    rows: list[dict] = []
    start = 0
    with httpx.Client(timeout=25.0) as client:
        while True:
            params = {
                "from": from_date.isoformat(),
                "till": to_date.isoformat(),
                "start": start,
                "iss.meta": "off",
            }
            r = client.get(url, params=params)
            r.raise_for_status()
            block = r.json().get("history", {})
            cols = block.get("columns", [])
            raw = block.get("data", [])
            if not raw:
                break
            for row in raw:
                rec = dict(zip(cols, row))
                close = rec.get("CLOSE")
                if close is None:
                    continue
                rows.append({
                    "date": datetime.strptime(rec["TRADEDATE"], "%Y-%m-%d").date(),
                    "open": rec.get("OPEN"),
                    "high": rec.get("HIGH"),
                    "low": rec.get("LOW"),
                    "close": float(close),
                    "volume": rec.get("VOLUME"),
                })
            start += len(raw)
            if len(raw) < 100:
                break
            time.sleep(0.15)
    log.info(f"MOEX {ticker}: {len(rows)} rows")
    return rows


def _fetch_crypto_history(ticker: str, from_date: date, to_date: date) -> list[dict]:
    symbol = ticker.upper().replace("USD", "USDT")
    url = f"{settings.binance_base_url}/api/v3/klines"
    start_ms = int(datetime.combine(from_date, datetime.min.time()).timestamp() * 1000)
    end_ms = int(datetime.combine(to_date, datetime.min.time()).timestamp() * 1000)
    rows: list[dict] = []
    with httpx.Client(timeout=20.0) as client:
        while start_ms < end_ms:
            r = client.get(url, params={
                "symbol": symbol, "interval": "1d",
                "startTime": start_ms, "endTime": end_ms, "limit": 1000,
            })
            r.raise_for_status()
            data = r.json()
            if not data:
                break
            for k in data:
                rows.append({
                    "date": datetime.utcfromtimestamp(k[0] / 1000).date(),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                })
            start_ms = data[-1][0] + 86400000
    return rows


def fetch_current_price(ticker: str) -> Optional[float]:
    ticker = ticker.upper()
    try:
        if is_crypto(ticker):
            symbol = ticker.replace("USD", "USDT")
            with httpx.Client(timeout=8.0) as client:
                r = client.get(f"{settings.binance_base_url}/api/v3/ticker/price",
                               params={"symbol": symbol})
                r.raise_for_status()
                return float(r.json()["price"])
        else:
            url = (
                f"{settings.moex_base_url}/engines/stock/markets/shares/"
                f"boards/{settings.moex_board}/securities/{ticker}.json"
            )
            with httpx.Client(timeout=8.0) as client:
                r = client.get(url, params={"iss.meta": "off"})
                r.raise_for_status()
                md = r.json().get("marketdata", {})
                cols = md.get("columns", [])
                data = md.get("data", [])
                if not data:
                    return None
                rec = dict(zip(cols, data[0]))
                price = rec.get("LAST") or rec.get("MARKETPRICE") or rec.get("LEGALCLOSEPRICE")
                return float(price) if price else None
    except Exception as e:
        log.warning(f"fetch_current_price {ticker}: {e}")
        return None


def available_tickers() -> list[str]:
    return sorted(MOEX_TICKERS | CRYPTO_TICKERS)