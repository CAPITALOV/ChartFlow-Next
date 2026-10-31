#!/usr/bin/env bash
# ChartFlow — полный деплой на сервер (Ubuntu + ISPmanager + systemd + Nginx)
# Идемпотентный: можно запускать повторно.
#
# Использование:
#   bash deploy.sh
#   bash deploy.sh --verbose       # подробный вывод
#   bash deploy.sh --skip-nginx    # не трогать Nginx
set -euo pipefail

# ---------- Конфигурация ----------
PROJECT_DIR="/var/www/sotis.org/data/www/pro.sotis.org"
VENV_PY="$PROJECT_DIR/.venv/bin/python"
VENV_PIP="$PROJECT_DIR/.venv/bin/pip"
SERVICE="chartflow"
SERVICE_FILE="/etc/systemd/system/${SERVICE}.service"
DOMAIN="pro.sotis.org"
VHOST="/etc/nginx/vhosts/sotis.org/${DOMAIN}.conf"
SNIPPET="/etc/nginx/snippets/chartflow-api.conf"
SNIPPET_INCLUDE="include ${SNIPPET};"
PORT="8000"

VERBOSE=0
SKIP_NGINX=0
for arg in "$@"; do
    case "$arg" in
        --verbose) VERBOSE=1 ;;
        --skip-nginx) SKIP_NGINX=1 ;;
    esac
done

# ---------- Цвета / хелперы ----------
if [[ -t 1 ]]; then
    G="\033[32m"; Y="\033[33m"; R="\033[31m"; B="\033[36m"; D="\033[90m"; N="\033[0m"
else
    G=""; Y=""; R=""; B=""; D=""; N=""
fi
step()  { echo -e "\n${B}▶ $*${N}"; }
say()   { echo -e "  ${D}$*${N}"; }
ok()    { echo -e "  ${G}✓${N} $*"; }
warn()  { echo -e "  ${Y}⚠${N} $*"; }
err()   { echo -e "  ${R}✗${N} $*"; }
die()   { err "$*"; exit 1; }

run() {
    if [[ $VERBOSE -eq 1 ]]; then "$@"; else "$@" >/dev/null 2>&1; fi
}

# ---------- Проверки ----------
[[ $EUID -eq 0 ]] || die "Запускайте от root (sudo bash deploy.sh)"
[[ -d "$PROJECT_DIR" ]] || die "Не найдена папка проекта: $PROJECT_DIR"
cd "$PROJECT_DIR"
[[ -f main.py ]] || die "В $PROJECT_DIR нет main.py"
[[ -x "$VENV_PY" ]] || die "Не найден $VENV_PY — сначала создайте .venv"
ok "Проект: $PROJECT_DIR"

# ---------- 1. requirements.txt ----------
step "1. Проверяю requirements.txt"
if grep -qE '^sqlalchemy\[asyncio\]' requirements.txt 2>/dev/null; then
    ok "sqlalchemy[asyncio] уже указан"
else
    say "Меняю 'sqlalchemy>=...' на 'sqlalchemy[asyncio]>=...'"
    sed -i 's|^sqlalchemy>=.*|sqlalchemy[asyncio]>=2.0.36|' requirements.txt
    grep -q '^greenlet' requirements.txt || echo 'greenlet>=3.1.0' >> requirements.txt
    ok "requirements.txt обновлён"
fi

# ---------- 2. greenlet ----------
step "2. Проверяю greenlet"
if "$VENV_PY" -c "import greenlet" 2>/dev/null; then
    ok "greenlet уже установлен"
else
    say "Устанавливаю..."
    run "$VENV_PIP" install "sqlalchemy[asyncio]>=2.0.36"
    ok "greenlet установлен"
fi

# ---------- 3. Импорт main ----------
step "3. Проверяю импорт main.py"
if IMPORT_ERR=$("$VENV_PY" -c "import main" 2>&1); then
    ok "main импортируется без ошибок"
else
    err "Импорт упал:"
    echo "$IMPORT_ERR" | tail -30
    die "Исправьте ошибку выше и запустите скрипт снова"
fi

# ---------- 4. .env ----------
step "4. Проверяю .env"
if [[ -f .env ]]; then
    ok ".env уже существует — не трогаю"
    ADMIN_USER_VAL=$(grep -E '^ADMIN_USER=' .env | cut -d= -f2- || echo "admin")
    ADMIN_PASS_VAL=$(grep -E '^ADMIN_PASSWORD=' .env | cut -d= -f2- || echo "<из .env>")
else
    say "Создаю .env с рандомными секретами..."
    GEN() { "$VENV_PY" -c "import secrets; print(secrets.token_urlsafe(48))"; }
    ADMIN_USER_VAL="admin"
    ADMIN_PASS_VAL=$(GEN | head -c 24)
    cat > .env <<EOF
DATABASE_URL=sqlite:///./chartflow.db
JWT_SECRET=$(GEN)
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=10080

ADMIN_USER=${ADMIN_USER_VAL}
ADMIN_PASSWORD=${ADMIN_PASS_VAL}
ADMIN_SECRET_KEY=$(GEN)

MOEX_BASE_URL=https://iss.moex.com/iss
MOEX_BOARD=TQBR
BINANCE_BASE_URL=https://api.binance.com

DEFAULT_HISTORY_DAYS=730
MIN_HISTORY_POINTS=60
VERIFY_HOUR_MSK=19
VERIFY_MINUTE_MSK=15
EOF
    chmod 600 .env
    ok ".env создан (chmod 600)"
fi

# ---------- 5. systemd ----------
step "5. Проверяю systemd unit"
EXPECTED_EXEC="ExecStart=${PROJECT_DIR}/.venv/bin/uvicorn main:app --host 127.0.0.1 --port ${PORT}"
if [[ -f "$SERVICE_FILE" ]] && grep -qF "$EXPECTED_EXEC" "$SERVICE_FILE"; then
    ok "Unit уже использует .venv"
else
    say "Перезаписываю $SERVICE_FILE"
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=ChartFlow FastAPI Engine
After=network.target

[Service]
User=root
WorkingDirectory=${PROJECT_DIR}
Environment="PATH=${PROJECT_DIR}/.venv/bin"
ExecStart=${PROJECT_DIR}/.venv/bin/uvicorn main:app --host 127.0.0.1 --port ${PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable "${SERVICE}" >/dev/null 2>&1 || true
    ok "Unit обновлён"
fi

# ---------- 6. Перезапуск ----------
step "6. Перезапускаю $SERVICE"
systemctl restart "$SERVICE"
sleep 2

if systemctl is-active --quiet "$SERVICE"; then
    ok "Служба активна"
else
    err "Служба упала. Лог:"
    journalctl -u "$SERVICE" -n 40 --no-pager | sed 's/^/    /'
    die "Разберитесь с ошибкой выше"
fi

# ---------- 7. Локальная проверка API ----------
step "7. Проверяю API на 127.0.0.1:${PORT}"
sleep 1
ROOT_JSON=$(curl -sf "http://127.0.0.1:${PORT}/" || echo "")
[[ -n "$ROOT_JSON" ]] || die "FastAPI не отвечает на / — смотрите journalctl -u $SERVICE -n 50"
ok "GET / → $(echo "$ROOT_JSON" | head -c 80)..."

MODELS_JSON=$(curl -sf "http://127.0.0.1:${PORT}/api/v1/models" || echo "")
[[ -n "$MODELS_JSON" ]] || die "GET /api/v1/models вернул ошибку"
ok "GET /api/v1/models → $MODELS_JSON"

# ---------- 8. Nginx ----------
if [[ $SKIP_NGINX -eq 1 ]]; then
    warn "Пропускаю настройку Nginx (--skip-nginx)"
else
    step "8. Настраиваю Nginx"

    if [[ ! -f "$VHOST" ]]; then
        warn "Не найден $VHOST — ISPmanager не создал vhost для $DOMAIN"
        warn "Создайте домен в ISPmanager и запустите скрипт снова"
        SKIP_NGINX=1
    fi
fi

if [[ $SKIP_NGINX -eq 0 ]]; then
    # 8a. Удаляем старые ручные конфиги, которые конфликтуют
    for old in /etc/nginx/conf.d/pro_sotis_main.conf /etc/nginx/conf.d/pro_sotis_proxy.conf /etc/nginx/conf.d/pro_sotis_clean.conf /etc/nginx/conf.d/chartflow_proxy.conf; do
        if [[ -f "$old" ]]; then
            rm -f "$old"
            ok "Удалён конфликтующий конфиг: $old"
        fi
    done

    # 8b. Создаём snippet
    mkdir -p /etc/nginx/snippets
    cat > "$SNIPPET" <<'NGINX'
# ChartFlow FastAPI proxy (auto-generated by deploy.sh)
location /api/ {
    proxy_pass http://127.0.0.1:8000/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 60s;
}
location /docs {
    proxy_pass http://127.0.0.1:8000/docs;
    proxy_set_header Host $host;
}
location /redoc {
    proxy_pass http://127.0.0.1:8000/redoc;
    proxy_set_header Host $host;
}
location /openapi.json {
    proxy_pass http://127.0.0.1:8000/openapi.json;
    proxy_set_header Host $host;
}
location /admin {
    proxy_pass http://127.0.0.1:8000/admin;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
NGINX
    ok "Snippet создан: $SNIPPET"

    # 8c. Добавляем include в vhost (с бэкапом)
    if grep -qF "$SNIPPET_INCLUDE" "$VHOST" 2>/dev/null; then
        ok "Include уже есть в vhost"
    else
        BACKUP="${VHOST}.bak.$(date +%Y%m%d-%H%M%S)"
        cp -a "$VHOST" "$BACKUP"
        say "Бэкап vhost: $BACKUP"

        # Вставляем include сразу после каждой строки, открывающей server {
        awk -v inc="    ${SNIPPET_INCLUDE}" '
            /^[[:space:]]*server[[:space:]]*\{/ {
                print
                print inc
                next
            }
            { print }
        ' "$BACKUP" > "$VHOST"

        ok "Include добавлен в vhost"
    fi

    # 8d. Проверяем конфиг и перезагружаем
    if nginx -t >/dev/null 2>&1; then
        systemctl reload nginx
        ok "Nginx перезагружен"
    else
        err "nginx -t упал — восстанавливаю бэкап"
        if [[ -n "${BACKUP:-}" && -f "$BACKUP" ]]; then
            cp -a "$BACKUP" "$VHOST"
            nginx -t >/dev/null 2>&1 && systemctl reload nginx || true
            err "Бэкап восстановлен. Проверьте конфиг вручную:"
            nginx -t 2>&1 | sed 's/^/    /'
        fi
        die "Разберитесь с ошибкой Nginx"
    fi
fi

# ---------- 9. Публичная проверка ----------
if [[ $SKIP_NGINX -eq 0 ]]; then
    step "9. Проверяю публичный доступ https://${DOMAIN}"
    sleep 1
    if curl -skf "https://${DOMAIN}/api/v1/models" >/dev/null 2>&1; then
        ok "https://${DOMAIN}/api/v1/models отвечает"
    else
        warn "Через домен пока не отвечает (SSL/ISPmanager/propagation?)"
        warn "Проверьте вручную: curl -I https://${DOMAIN}/docs"
    fi
fi

# ---------- 10. Smoke-тест прогноза ----------
step "10. Smoke-тест: загрузка SBER + прогноз"
say "Загружаю историю SBER (может занять 5-15 сек)..."
BACKFILL=$(curl -sf -X POST "http://127.0.0.1:${PORT}/api/v1/backfill/SBER?days=730" 2>/dev/null || echo "")
if [[ -n "$BACKFILL" ]]; then
    ok "Backfill: $BACKFILL"
else
    warn "Backfill не сработал (MOEX может быть недоступен с сервера)"
fi

say "Формирую прогноз holt_winters на 14 дней..."
FORECAST=$(curl -sf -X POST "http://127.0.0.1:${PORT}/api/v1/forecast" \
    -H "Content-Type: application/json" \
    -d '{"ticker":"SBER","horizon_days":14,"algorithm":"holt_winters"}' 2>/dev/null || echo "")
if [[ -n "$FORECAST" ]]; then
    TGT=$(echo "$FORECAST" | "$VENV_PY" -c "import sys,json;d=json.load(sys.stdin);print(f\"target={d['target_price']} price={d['current_price']} model={d['model']}\")" 2>/dev/null || echo "ok")
    ok "Прогноз создан: $TGT"
else
    warn "Прогноз не создан — проверьте историю (backfill) и journalctl"
fi

# ---------- Финал ----------
echo
echo -e "${G}════════════════════════════════════════════════════════════${N}"
echo -e "${G}  Деплой завершён успешно${N}"
echo -e "${G}════════════════════════════════════════════════════════════${N}"
echo
echo -e "  ${B}URL-адреса:${N}"
echo -e "    Дашборд:  https://${DOMAIN}/dashboard.html"
echo -e "    Swagger:  https://${DOMAIN}/docs"
echo -e "    Админка:  https://${DOMAIN}/admin"
echo -e "    API:      https://${DOMAIN}/api/v1/models"
echo
echo -e "  ${B}Доступ в админку:${N}"
echo -e "    Логин:    ${ADMIN_USER_VAL}"
echo -e "    Пароль:   ${ADMIN_PASS_VAL}"
echo -e "    ${Y}(пароль хранится в ${PROJECT_DIR}/.env — сохраните его)${N}"
echo
echo -e "  ${B}Полезные команды:${N}"
echo -e "    systemctl status ${SERVICE}       # статус службы"
echo -e "    journalctl -u ${SERVICE} -f       # live-логи"
echo -e "    curl http://127.0.0.1:${PORT}/    # локальная проверка"
echo