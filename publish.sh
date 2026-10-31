#!/usr/bin/env bash
# ChartFlow — безопасная публикация в GitHub
# Использование:
#   bash publish.sh                        # интерактивно
#   bash publish.sh -m "Commit message"    # свой коммит
#   bash publish.sh --force-history        # перезаписать историю (осторожно!)
#   bash publish.sh --repo git@github.com:USER/REPO.git
set -euo pipefail

# ---------- Параметры ----------
REPO_URL="${REPO_URL:-https://github.com/CAPITALOV/ChartFlow-Next.git}"
COMMIT_MSG=""
FORCE_HISTORY=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        -m) COMMIT_MSG="$2"; shift 2 ;;
        --repo) REPO_URL="$2"; shift 2 ;;
        --force-history) FORCE_HISTORY=1; shift ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \?//'; exit 0 ;;
        *) echo "Неизвестный аргумент: $1"; exit 1 ;;
    esac
done

# ---------- Цвета ----------
if [[ -t 1 ]]; then G="\033[32m"; Y="\033[33m"; R="\033[31m"; B="\033[36m"; N="\033[0m"
else G=""; Y=""; R=""; B=""; N=""; fi
say()  { echo -e "${B}[INFO]${N} $*"; }
ok()   { echo -e "${G}[ OK ]${N} $*"; }
warn() { echo -e "${Y}[WARN]${N} $*"; }
err()  { echo -e "${R}[FAIL]${N} $*"; }
die()  { err "$*"; exit 1; }

# ---------- Проверки ----------
command -v git >/dev/null || die "git не найден"
[[ -f "main.py" ]] || die "Запускайте скрипт из корня проекта (нет main.py)"
[[ -f ".gitignore" ]] || die "Нет .gitignore — опубликуете секреты. Создайте его сначала."

# ---------- Жёсткая защита от утечки секретов ----------
say "Проверяю, что секреты не попадут в git..."
LEAK=0
for f in .env chartflow.db chartflow.db-wal chartflow.db-shm; do
    if [[ -f "$f" ]] && ! git check-ignore -q "$f" 2>/dev/null; then
        # .gitignore ещё не действует если репо не инициализировано — проверим вручную
        case "$f" in
            .env*|*.db*)
                err "Файл '$f' НЕ в .gitignore (или git ещё не инициализирован)."
                LEAK=1
                ;;
        esac
    fi
done
# Отдельно: если .env нет в .gitignore по содержимому
if ! grep -qE '^\.env$' .gitignore; then
    err ".gitignore не содержит '.env'. Добавьте строку и повторите."
    LEAK=1
fi
[[ $LEAK -eq 1 ]] && die "Исправьте .gitignore перед публикацией."

# Проверка, что в коде нет хардкод-секретов из примеров
if grep -rE '(JWT_SECRET\s*=\s*"[^"]{8,}"|ADMIN_PASSWORD\s*=\s*"[^"]+")' \
    --include='*.py' . 2>/dev/null | grep -v config.py | grep -v '.env'; then
    warn "Найдены потенциально захардкоженные секреты (см. выше). Проверьте."
fi

ok "Секреты защищены .gitignore"

# ---------- Git init / проверка remote ----------
if [[ ! -d ".git" ]]; then
    say "Инициализирую git-репозиторий..."
    git init -b main
fi

CURRENT_REMOTE="$(git remote get-url origin 2>/dev/null || echo "")"
if [[ -z "$CURRENT_REMOTE" ]]; then
    say "Добавляю remote origin → $REPO_URL"
    git remote add origin "$REPO_URL"
elif [[ "$CURRENT_REMOTE" != "$REPO_URL" ]]; then
    warn "Текущий origin: $CURRENT_REMOTE"
    warn "Новый:            $REPO_URL"
    read -p "Заменить? [y/N] " ans
    if [[ "${ans,,}" == "y" ]]; then
        git remote set-url origin "$REPO_URL"
    fi
fi

# ---------- Проверка user.name/email ----------
if ! git config user.email >/dev/null; then
    die "Не настроен git user.email. Выполните:
    git config --global user.email 'you@example.com'
    git config --global user.name  'Your Name'"
fi

# ---------- Force history ----------
if [[ $FORCE_HISTORY -eq 1 ]]; then
    warn "!!! Будет удалена вся история git и записан один корневой коммит."
    read -p "Продолжить? Введите YES заглавными: " ans
    [[ "$ans" == "YES" ]] || die "Отменено."
    rm -rf .git
    git init -b main
    git remote add origin "$REPO_URL"
fi

# ---------- Add + status ----------
say "Индексирую файлы..."
git add -A

echo
say "Файлы, которые попадут в коммит:"
git diff --cached --name-status | sed 's/^/    /'
echo

# Если что-то из "запрещённых" попало в staged — аварийный стоп
if git diff --cached --name-only | grep -qE '(^|/)\.env$|\.db$|\.sqlite$|(^|/)\.venv/'; then
    err "В staged попали секреты/БД/venv. Удалите их из индекса:"
    echo "    git reset HEAD <файл>"
    die "Публикация отменена."
fi

# ---------- Commit ----------
if git diff --cached --quiet; then
    warn "Нечего коммитить — всё уже закоммичено."
else
    if [[ -z "$COMMIT_MSG" ]]; then
        COMMIT_MSG="Release v3.0: FastAPI + SQLAlchemy + SQLAdmin, real models & verification"
    fi
    say "Коммит: $COMMIT_MSG"
    git commit -m "$COMMIT_MSG"
fi

# ---------- Push ----------
BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null || echo main)"

say "Пушу в $REPO_URL (branch: $BRANCH)..."
if git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
    say "Ветка '$BRANCH' уже есть на remote."
    if [[ $FORCE_HISTORY -eq 1 ]]; then
        warn "История была перезаписана — форсирую push (--force-with-lease)."
        git push --force-with-lease origin "$BRANCH"
    else
        git push origin "$BRANCH"
    fi
else
    say "Ветки '$BRANCH' на remote нет — обычный push."
    git push -u origin "$BRANCH"
fi

echo
ok "Опубликовано: $REPO_URL"
echo "   Проверьте: ${REPO_URL%.git}"
echo "   Admin:  http://<домен>/admin"
echo "   API:    http://<домен>/docs"