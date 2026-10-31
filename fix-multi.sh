#!/usr/bin/env bash
set -u
cd /var/www/sotis.org/data/www/pro.sotis.org

if [[ -t 1 ]]; then G="\033[32m"; Y="\033[33m"; R="\033[31m"; B="\033[36m"; N="\033[0m"
else G=""; Y=""; R=""; B=""; N=""; fi
ok()   { echo -e "${G}✓${N} $*"; }
warn() { echo -e "${Y}⚠${N} $*"; }
err()  { echo -e "${R}✗${N} $*"; }
info() { echo -e "${B}→${N} $*"; }

echo "=== 1. Проверка файла на диске ==="
if [[ ! -f main.py ]]; then
    err "main.py отсутствует!"
    exit 1
fi
SIZE=$(stat -c%s main.py)
LINES=$(wc -l < main.py)
info "main.py: ${SIZE} байт, ${LINES} строк"

if grep -q "forecast/multi" main.py; then
    ok "Содержит /api/v1/forecast/multi"
    HAS_MULTI=1
else
    err "НЕ содержит /api/v1/forecast/multi"
    HAS_MULTI=0
fi

VER_FILE=$(grep -oE 'version="[0-9.]+"' main.py | head -1)
info "Версия в файле: ${VER_FILE:-<не найдена>}"

# Проверим бэкапы nano — вдруг main.py~ содержит правильную версию
if [[ $HAS_MULTI -eq 0 ]] && [[ -f main.py~ ]]; then
    warn "Найден main.py~ — возможно, это сохранённая версия из nano"
    if grep -q "forecast/multi" main.py~; then
        info "main.py~ СОДЕРЖИТ multi-эндпоинт — восстанавливаю из бэкапа"
        cp main.py main.py.old
        mv main.py~ main.py
        HAS_MULTI=1
        ok "main.py восстановлен из main.py~"
    fi
fi

if [[ $HAS_MULTI -eq 0 ]]; then
    err "Файл не содержит multi-эндпоинт. Нужно пересохранить main.py версии 3.1.0."
    echo
    echo "Вариант 1 (ручной): открыть nano main.py, вставить полный код из чата,"
    echo "  сохранить через Ctrl+O → Enter → Ctrl+X"
    echo
    echo "Вариант 2 (автоматический): скачать с GitHub, если коммит 858e451 уже содержит v3.1.0"
    echo "  git show HEAD:main.py | grep -q 'forecast/multi' && echo 'В коммите есть!' || echo 'В коммите нет'"
    exit 1
fi

echo
echo "=== 2. Проверка импорта ==="
if .venv/bin/python -c "import main" 2>/tmp/import.err; then
    ok "main.py импортируется без ошибок"
else
    err "Ошибка импорта:"
    tail -20 /tmp/import.err
    exit 1
fi

echo
echo "=== 3. Перезапуск службы ==="
systemctl restart chartflow
sleep 3
if systemctl is-active --quiet chartflow; then
    ok "chartflow активна"
else
    err "chartflow не запустилась, лог:"
    journalctl -u chartflow -n 30 --no-pager | tail -20
    exit 1
fi

echo
echo "=== 4. Версия живого API ==="
LIVE_JSON=$(curl -s http://127.0.0.1:8000/)
LIVE_VER=$(echo "$LIVE_JSON" | .venv/bin/python -c "import sys,json;print(json.load(sys.stdin).get('version','?'))")
info "Версия живого API: $LIVE_VER"
if [[ "$LIVE_VER" == "3.1.0" ]]; then
    ok "Версия правильная"
else
    warn "Версия не 3.1.0 — возможно, процесс не перезагрузился"
fi

echo
echo "=== 5. Проверка OpenAPI ==="
if curl -s http://127.0.0.1:8000/openapi.json | grep -q "forecast/multi"; then
    ok "Эндпоинт /api/v1/forecast/multi зарегистрирован"
else
    err "Эндпоинт /api/v1/forecast/multi ОТСУТСТВУЕТ в OpenAPI"
    exit 1
fi

echo
echo "=== 6. Smoke-тест multi ==="
curl -s -m 120 -X POST http://127.0.0.1:8000/api/v1/forecast/multi \
  -H "Content-Type: application/json" \
  -d '{"ticker":"SBER","horizon_days":14}' \
  -o /tmp/multi.json -w "HTTP %{http_code}  время %{time_total}s  размер %{size_download}B\n"

if [[ -s /tmp/multi.json ]]; then
    .venv/bin/python - <<'PY'
import json
d = json.load(open("/tmp/multi.json"))
print(f"  Тикер:       {d['ticker']}")
print(f"  Цена:        {d['current_price']} ₽")
print(f"  Серий:       {len(d['series'])}")
for s in d['series']:
    mape = f"{s['mape']}%" if s['mape'] is not None else "—"
    print(f"    - {s['model']:<14} MAPE {mape:<8} target {s['target_price']} ₽")
print(f"  Лучшая:      {d.get('best_model')} (MAPE {d.get('best_mape')}%)")
PY
else
    err "Пустой ответ"
    cat /tmp/multi.json
fi