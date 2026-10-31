#!/usr/bin/env bash
# ChartFlow — безопасный push на GitHub.
# Токен запрашивается интерактивно, не сохраняется в файлах/истории.
#
# Использование:
#   bash push.sh                          # обычный push
#   bash push.sh --force                  # форс-пуш (перезапись истории)
#   bash push.sh --cleanup                # удалить устаревшие файлы из repo
#   bash push.sh --cleanup --force        # всё сразу
set -euo pipefail

REPO_URL="https://github.com/CAPITALOV/ChartFlow-Next.git"
REPO_HTTPS="https://github.com/CAPITALOV/ChartFlow-Next"
PROJECT_DIR="/var/www/sotis.org/data/www/pro.sotis.org"
BRANCH="main"

FORCE=0
CLEANUP=0
for a in "$@"; do
    case "$a" in
        --force)   FORCE=1 ;;
        --cleanup) CLEANUP=1 ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \?//'
            exit 0 ;;
    esac
done

cd "$PROJECT_DIR"

# ---------- Цвета ----------
if [[ -t 1 ]]; then G="\033[32m"; Y="\033[33m"; R="\033[31m"; B="\033[36m"; D="\033[90m"; N="\033[0m"
else G=""; Y=""; R=""; B=""; D=""; N=""; fi
step() { echo -e "\n${B}▶ $*${N}"; }
ok()   { echo -e "  ${G}✓${N} $*"; }
warn() { echo -e "  ${Y}⚠${N} $*"; }
err()  { echo -e "  ${R}✗${N} $*"; }
die()  { err "$*"; exit 1; }

# ---------- Проверки ----------
[[ -d .git ]] || die "Нет .git — запустите из корня проекта"
[[ -f .gitignore ]] || die "Нет .gitignore — риск утечки секретов"

step "Проверяю защиту от утечек"
# .env и .db должны быть в .gitignore
for pat in '\.env$' '\.db' '\.venv'; do
    grep -qE "$pat" .gitignore || die ".gitignore не содержит $pat"
done

# Ничего запрещённого в staged?
STAGED_BAD=$(git diff --cached --name-only 2>/dev/null | grep -E '(^|/)\.env$|\.db$|(^|/)\.venv/' || true)
[[ -z "$STAGED_BAD" ]] || die "В staged есть секреты/БД: $STAGED_BAD"
ok "Секреты защищены"

# ---------- Git identity ----------
step "Проверяю git config"
if ! git config user.email >/dev/null 2>&1; then
    say_email="${GIT_EMAIL:-capitalov@users.noreply.github.com}"
    say_name="${GIT_NAME:-CAPITALOV}"
    warn "user.email не задан — устанавливаю $say_email"
    git config user.email "$say_email"
    git config user.name "$say_name"
fi
ok "user.name=$(git config user.name), user.email=$(git config user.email)"

# ---------- Remote ----------
step "Настраиваю remote"
git remote set-url origin "$REPO_URL" 2>/dev/null || git remote add origin "$REPO_URL"
ok "origin → $REPO_URL"

# ---------- Cleanup устаревших файлов ----------
if [[ $CLEANUP -eq 1 ]]; then
    step "Удаляю устаревшие файлы из индекса git"
    LEGACY=(
        "chartflow_dashboard.html"
        "index.html.html"
        "python_fastapi_backend_engine.py"
        "python_fastapi_backend_engine (1).py"
        "gemini-code-1793476831034.sh"
        "gemini-code-1793477016352.sh"
    )
    REMOVED=0
    for f in "${LEGACY[@]}"; do
        if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
            git rm --cached --quiet "$f"
            ok "удалён из индекса: $f"
            REMOVED=$((REMOVED+1))
        fi
    done
    if [[ $REMOVED -gt 0 ]]; then
        git commit -m "Remove obsolete legacy files from repository" \
            || warn "Нечего коммитить"
        ok "Коммит-очистка создан"
    else
        warn "Устаревших файлов в индексе нет"
    fi
fi

# ---------- Add ----------
step "Индексирую изменения"
git add -A
if git diff --cached --quiet; then
    warn "Нет изменений для коммита"
else
    CHANGES=$(git diff --cached --shortstat)
    ok "Изменения: $CHANGES"
fi

# ---------- Commit ----------
step "Коммит"
if git diff --cached --quiet; then
    warn "Пропускаю — нечего коммитить"
else
    DEFAULT_MSG="Update: $(date +%Y-%m-%d\ %H:%M) MSK"
    [[ $CLEANUP -eq 1 ]] && DEFAULT_MSG="Cleanup legacy files + deploy"
    git commit -m "${COMMIT_MSG:-$DEFAULT_MSG}"
    ok "Коммит создан"
fi

# ---------- Запрос токена ----------
step "Аутентификация GitHub"
# Токен можно передать через env, если автоматизируете. Не храните в файлах!
TOKEN="${GH_TOKEN:-}"

if [[ -z "$TOKEN" ]]; then
    echo -e "${D}GitHub не принимает пароли. Нужен Personal Access Token.${N}"
    echo -e "${D}Создать: https://github.com/settings/tokens → 'repo' scope${N}"
    echo -n "Token (ghp_..., ввод скрыт): "
    read -rs TOKEN
    echo
fi

[[ -n "$TOKEN" ]] || die "Токен не введён"
[[ "$TOKEN" =~ ^(ghp_|github_pat_) ]] || warn "Токен не похож на GitHub PAT (ghp_... / github_pat_...)"

# Записываем URL с токеном ТОЛЬКО на время push
PUSH_URL="https://${TOKEN}@github.com/CAPITALOV/ChartFlow-Next.git"
git remote set-url origin "$PUSH_URL"

cleanup_token() {
    git remote set-url origin "$REPO_URL" 2>/dev/null || true
    unset TOKEN PUSH_URL
}
trap cleanup_token EXIT INT TERM

# ---------- Push ----------
step "Push в $BRANCH"
if [[ $FORCE -eq 1 ]]; then
    warn "Форс-пуш: удалённая история будет перезаписана"
    git push -u origin "$BRANCH" --force
else
    git push -u origin "$BRANCH"
fi

# ---------- Итог ----------
echo
echo -e "${G}════════════════════════════════════════════════════════${N}"
echo -e "${G}  Push успешен${N}"
echo -e "${G}════════════════════════════════════════════════════════${N}"
echo
echo "  Репозиторий: $REPO_HTTPS"
echo "  Ветка:       $BRANCH"
echo "  Коммит:      $(git rev-parse --short HEAD)"
echo
echo -e "${Y}  Токен удалён из .git/config (trap)${N}"
echo