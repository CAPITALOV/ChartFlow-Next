# ChartFlow — Forecast Engine

Платформа прогнозирования котировок (MOEX + крипто) с **реальной верификацией**:
каждый прогноз сохраняется в БД, и через N дней автоматически сверяется с
фактической ценой. MAPE/MAE/RMSE считаются честно по завершённым прогнозам,
а не выдумываются.

Замена PHP-версии `StockForecast-by-KAPITALOV` на современный стек без PHP.

[![Python](https://img.shields.io/badge/python-3.12%20%7C%203.14-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## Возможности

- 📈 **Реальные модели**: naive, moving average, Holt-Winters (exp. smoothing), ARIMA(2,1,1)
- 🌐 **Реальные данные**: MOEX ISS (`TQBR`) для акций, Binance для крипто
- 🎯 **Честная верификация**: каждый прогноз сохраняется в `ForecastRun` + `ForecastPoint`, ежедневная задача сверяет предсказания с фактом по расписанию
- 📊 **Реальный MAPE**: считается по завершённым прогнозам, а не подставляется формулой
- 🔐 **JWT-авторизация**: пользователи в БД, bcrypt-хеши паролей
- 🛠 **Админка из коробки**: SQLAdmin (`/admin`) для управления тикерами, прогнозами, историей, избранным
- 🎨 **Тёмный дашборд**: `dashboard.html` на Tailwind + Canvas, тянет данные из API
- ⏰ **Планировщик**: APScheduler, верификация Mon-Fri в 19:15 MSK
- 📦 **SQLite по умолчанию**: один файл — можно переключить на PostgreSQL одной строкой в `.env`

## Архитектура

```
┌─────────────┐   ┌──────────────┐   ┌────────────────┐
│ dashboard   │──▶│ FastAPI      │──▶│ SQLAlchemy ORM │
│ .html       │   │ (main.py)    │   │ (SQLite/Postgres)
└─────────────┘   └──────┬───────┘   └────────┬───────┘
                         │                    │
                         ▼                    ▼
                  ┌────────────┐       ┌───────────────┐
                  │ moex_client│       │  ForecastRun  │
                  │ forecaster │       │ ForecastPoint │
                  └────────────┘       └───────┬───────┘
                         ▲                     │
                         │                     ▼
                  ┌──────┴─────┐        ┌────────────┐
                  │ APScheduler│───────▶│  verifier  │
                  │ (cron)     │        │ (MAPE/MAE) │
                  └────────────┘        └────────────┘
```

## Быстрый старт

```bash
git clone https://github.com/CAPITALOV/ChartFlow-Next.git
cd ChartFlow-Next

python3.12 -m venv .venv          # или python3.14
.venv/bin/pip install -r requirements.txt

cp .env.example .env
# отредактируйте .env: JWT_SECRET, ADMIN_PASSWORD, ADMIN_SECRET_KEY

.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Откройте:

- **API-доки:** http://127.0.0.1:8000/docs
- **Админка:** http://127.0.0.1:8000/admin (логин/пароль из `.env`)
- **Дашборд:** откройте `dashboard.html` в браузере или раздайте любым web-сервером

## Первые прогнозы

```bash
# 1. Загрузить историю SBER за 2 года
curl -X POST "http://127.0.0.1:8000/api/v1/backfill/SBER?days=730"

# 2. Сформировать прогноз
curl -X POST http://127.0.0.1:8000/api/v1/forecast \
  -H "Content-Type: application/json" \
  -d '{"ticker":"SBER","horizon_days":14,"algorithm":"holt_winters"}'

# 3. Посмотреть историю прогнозов по тикеру
curl http://127.0.0.1:8000/api/v1/runs/SBER

# 4. Через N дней — верификация (или вручную)
curl -X POST http://127.0.0.1:8000/api/v1/verify-now

# 5. Проверить честный MAPE по завершённым прогнозам
curl http://127.0.0.1:8000/api/v1/stats/SBER
```

## Стек

| Слой | Технология |
|---|---|
| API | FastAPI 0.115+, Pydantic v2 |
| ORM | SQLAlchemy 2.x |
| БД | SQLite (dev) / PostgreSQL (prod) |
| Аутентификация | JWT (`python-jose`), bcrypt (`passlib`) |
| Админка | SQLAdmin + Jinja2 |
| Планировщик | APScheduler (cron Europe/Moscow) |
| Модели | `statsmodels` (Holt-Winters, ARIMA), fallback на naive/MA без него |
| Данные | MOEX ISS API, Binance API (`httpx`) |
| Фронтенд | HTML + Tailwind CSS (CDN) + Canvas 2D |

## Про Python 3.14

`numpy`/`statsmodels` на момент релиза могут не иметь колёс под 3.14.
`install.sh` умеет обходить эту проблему: если pip падает — ставит всё
кроме тяжёлых пакетов, а `forecaster.py` работает в fallback-режиме
(`naive`/`moving_avg`). Для полноценных моделей используйте Python 3.12:

```bash
bash install.sh                      # умная установка
bash migrate-py312.sh                # перейти на 3.12 (если нужно)
```

## Конфигурация `.env`

| Переменная | Назначение |
|---|---|
| `DATABASE_URL` | `sqlite:///./chartflow.db` или `postgresql+psycopg2://user:pass@host/db` |
| `JWT_SECRET` | Секрет для подписи токенов (мин. 32 символа) |
| `ADMIN_USER` / `ADMIN_PASSWORD` | Учётка админа (создаётся при первом старте) |
| `ADMIN_SECRET_KEY` | Ключ сессии SQLAdmin |
| `VERIFY_HOUR_MSK` / `VERIFY_MINUTE_MSK` | Время ежедневной верификации |

## Roadmap

- [x] Реальные модели прогнозирования
- [x] Сохранение прогнозов + автоматическая верификация
- [x] Честный MAPE из завершённых прогнозов
- [x] JWT-авторизация + админка
- [ ] React-фронтенд (Vite + Tailwind + Lightweight Charts)
- [ ] Портфель и P&L по сигналам
- [ ] Prophet / LSTM (опционально)
- [ ] Telegram-бот с ежедневной сводкой прогнозов

## Лицензия

MIT — см. [LICENSE](LICENSE).