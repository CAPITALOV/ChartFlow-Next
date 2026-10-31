#!/usr/bin/env bash
# ChartFlow — умная установка зависимостей
# Умеет обходить проблемы Python 3.14 с numpy/statsmodels.
# Использование:
#   bash install.sh              # установка
#   bash install.sh --verbose    # с полным выводом pip
set -u

# -------- Настройки --------
VENV_PY="${VENV_PY:-/var/www/sotis.org/data/www/pro.sotis.org/.venv/bin/python3.14}"
VENV_PIP="${VENV_PIP:-/var/www/sotis.org/data/www/pro.sotis.org/.venv/bin/pip}"
REQ_FILE="${REQ_FILE:-requirements.txt}"
BUILD_REQ_FILE="requirements.build.txt"

VERBOSE=0
[[ "${1:-}" == "--verbose" ]] && VERBOSE=1

# -------- Цвета --------
if [[ -t 1 ]]; then
    G="\033[32m"; Y="\033[33m"; R="\033[31m"; B="\033[36m"; N="\033[0m"
else
    G=""; Y=""; R=""; B=""; N=""
fi

say()  { echo -e "${B}[INFO]${N} $*"; }
ok()   { echo -e "${G}[ OK ]${N} $*"; }
warn() { echo -e "${Y}[WARN]${N} $*"; }
err()  { echo -e "${R}[FAIL]${N} $*"; }
die()  { err "$*"; exit 1; }

# -------- Проверки окружения --------
[[ -x "$VENV_PY" ]] || die "Python не найден: $VENV_PY"
[[ -x "$VENV_PIP" ]] || die "pip не найден: $VENV_PIP"
[[ -f "$REQ_FILE" ]] || die "Не найден $REQ_FILE (запустите из корня проекта)"

PY_VER="$("$VENV_PY" -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
say "Python версия: ${PY_VER}"
say "pip: ${VENV_PIP}"
say "Файл зависимостей: ${REQ_FILE}"

# -------- Обновляем pip --------
say "Обновляю pip, setuptools, wheel..."
if [[ $VERBOSE -eq 1 ]]; then
    "$VENV_PIP" install --upgrade pip setuptools wheel
else
    "$VENV_PIP" install --quiet --upgrade pip setuptools wheel \
        || warn "Обновление pip завершилось с ошибкой — продолжаем"
fi

# -------- Попытка 1: установить всё целиком --------
say "Попытка установки всех зависимостей (это может занять 2-5 минут)..."

run_pip_full() {
    if [[ $VERBOSE -eq 1 ]]; then
        "$VENV_PIP" install -r "$REQ_FILE"
    else
        "$VENV_PIP" install --quiet -r "$REQ_FILE"
    fi
}

PIP_LOG="$(mktemp -t chartflow-pip.XXXXXX.log)"
if run_pip_full 2>"$PIP_LOG"; then
    ok "Все зависимости установлены."
    INSTALL_MODE="full"
else
    warn "Полная установка не удалась — смотрю, что именно сломалось..."
    if grep -qiE 'numpy|statsmodels|scipy' "$PIP_LOG"; then
        warn "Похоже, проблема в numpy / scipy / statsmodels (типично для Python 3.14)."
        INSTALL_MODE="fallback"
    else
        err "Установка упала не из-за numpy/statsmodels. Лог:"
        cat "$PIP_LOG"
        rm -f "$PIP_LOG"
        die "Разберитесь с ошибкой выше вручную."
    fi
fi

# -------- Fallback: без numpy/statsmodels --------
if [[ "${INSTALL_MODE:-}" == "fallback" ]]; then
    say "Собираю упрощённый набор зависимостей без numpy и statsmodels..."
    : > "$BUILD_REQ_FILE"
    while IFS= read -r line; do
        [[ -z "$line" || "$line" =~ ^# ]] && continue
        pkg="$(echo "$line" | sed -E 's/[>=<!~ ].*//' | tr -d '[:space:]')"
        case "$pkg" in
            numpy|statsmodels|scipy|pandas) continue ;;
        esac
        echo "$line" >> "$BUILD_REQ_FILE"
    done < "$REQ_FILE"

    say "Устанавливаю урезанный набор (pandas тоже пропускаем — он тянет numpy)..."
    say "Текущее содержимое ${BUILD_REQ_FILE}:"
    sed 's/^/    /' "$BUILD_REQ_FILE"

    if [[ $VERBOSE -eq 1 ]]; then
        "$VENV_PIP" install -r "$BUILD_REQ_FILE" || die "Даже урезанная установка не удалась"
    else
        "$VENV_PIP" install --quiet -r "$BUILD_REQ_FILE" || die "Даже урезанная установка не удалась"
    fi
    ok "Урезанный набор установлен. Приложение будет работать в режиме naive/moving_avg."
    rm -f "$BUILD_REQ_FILE"
fi
rm -f "$PIP_LOG"

# -------- Диагностика: что реально доступно --------
say "Диагностика после установки:"
"$VENV_PY" - <<'PY'
import importlib, sys

checks = [
    ("fastapi",        "FastAPI"),
    ("uvicorn",        "uvicorn"),
    ("sqlalchemy",     "SQLAlchemy"),
    ("pydantic",       "Pydantic"),
    ("pydantic_settings", "pydantic-settings"),
    ("httpx",          "httpx"),
    ("apscheduler",    "APScheduler"),
    ("passlib",        "passlib"),
    ("jose",           "python-jose"),
    ("sqladmin",       "SQLAdmin"),
    ("jinja2",         "Jinja2"),
    ("itsdangerous",   "itsdangerous"),
    ("python_multipart", "python-multipart"),
    ("email_validator", "email-validator"),
]
optional = [
    ("pandas",    "pandas"),
    ("numpy",     "numpy"),
    ("statsmodels", "statsmodels"),
]

def check(pkg, label):
    try:
        importlib.import_module(pkg)
        return f"  ✓ {label}"
    except Exception as e:
        return f"  ✗ {label}  ({type(e).__name__})"

print("Обязательные:")
for p, l in checks:
    print(check(p, l))
print("\nОпциональные (для продвинутых моделей):")
missing = []
for p, l in optional:
    line = check(p, l)
    print(line)
    if "✗" in line:
        missing.append(l)

print()
if missing:
    print(f"⚠  Не установлены: {', '.join(missing)}")
    print("   Прогноз будет работать в fallback-режиме (naive/moving_avg).")
    print("   Чтобы включить ARIMA/Holt-Winters, перейдите на Python 3.12:")
    print("     python3.12 -m venv .venv312")
    print("     .venv312/bin/pip install -r requirements.txt")
else:
    print("✓  Все модели доступны: naive, moving_avg, holt_winters, arima")

sys.exit(0)
PY

echo
ok "Установка завершена."
say "Запуск:"
echo "    ${VENV_PY%/python3.14}/uvicorn main:app --host 0.0.0.0 --port 8000 --reload"
echo
say "Проверка API:"
echo "    curl http://127.0.0.1:8000/"
echo
say "Админка: http://<домен>/admin  (логин/пароль из .env)"