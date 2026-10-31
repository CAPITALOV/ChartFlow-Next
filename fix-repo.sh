#!/usr/bin/env bash
# Удаляет legacy-файлы с диска и из git, делает чистый push.
# Токен запрашивается интерактивно, не сохраняется.
set -euo pipefail

PROJECT_DIR="/var/www/sotis.org/data/www/pro.sotis.org"
REPO_URL="https://github.com/CAPITALOV/ChartFlow-Next.git"
BRANCH="main"
cd "$PROJECT_DIR"

if [[ -t 1 ]]; then G="\033[32m"; Y="\033[33m"; R="\033[31m"; B="\033[36m"; D="\033[90m"; N="\033[0m"
else G=""; Y=""; R=""; B=""; D=""; N=""; fi
step() { echo -e "\n${B}▶ $*${N}"; }
ok()   { echo -e "  ${G}✓${N} $*"; }
warn() { echo -e "  ${Y}⚠${N} $*"; }
die()  { echo -e "  ${R}✗ $*${N}"; exit 1; }

[[ -d .git ]] || die "Нет .git"

# ---------- 1. Удаляем legacy-файлы с диска ----------
step "Удаляю legacy-файлы с диска"
LEGACY=(
    "chartflow_dashboard.html"
    "index.html.html"
    "python_fastapi_backend_engine.py"
    "python_fastapi_backend_engine (1).py"
    "gemini-code-1793476831034.sh"
    "gemini-code-1793477016352.sh"
)
for f in "${LEGACY[@]}"; do
    if [[ -f "$f" ]]; then
        rm -f "$f"
        ok "удалён: $f"
    fi
done

# ---------- 2. Чистим из индекса git ----------
step "Убираю legacy из индекса git"
for f in "${LEGACY[@]}"; do
    if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
        git rm --cached --quiet "$f"
        ok "git rm --cached: $f"
    fi
done

# ---------- 3. Проверяем, что .env/.db не попадут ----------
step "Проверяю защиту"
STAGED_BAD=$(git diff --cached --name-only 2>/dev/null | grep -E '(^|/)\.env$|\.db$' || true)
[[ -z "$STAGED_BAD" ]] || die "Секреты в staged: $STAGED_BAD"
ok "Секреты защищены"

# ---------- 4. Добавляем остальное и коммитим ----------
step "Коммичу"
git add -A
if git diff --cached --quiet; then
    warn "Нечего коммитить — файлы уже удалены"
else
    git commit -m "Purge legacy files from repository and disk"
    ok "Коммит: $(git rev-parse --short HEAD)"
fi

# ---------- 5. Показываем, что осталось в репо ----------
step "Файлы в индексе (топ-30)"
git ls-files | head -30 | sed 's/^/    /'
echo -e "    ${D}... всего: $(git ls-files | wc -l) файлов${N}"

# ---------- 6. Запрос токена ----------
step "Аутентификация"
TOKEN="${GH_TOKEN:-}"
if [[ -z "$TOKEN" ]]; then
    echo -e "${D}GitHub PAT (создать: https://github.com/settings/tokens, scope 'repo')${N}"
    echo -n "Token (ввод скрыт): "
    read -rs TOKEN
    echo
fi
[[ -n "$TOKEN" ]] || die "Токен не введён"

PUSH_URL="https://${TOKEN}@github.com/CAPITALOV/ChartFlow-Next.git"
git remote set-url origin "$PUSH_URL"
cleanup() { git remote set-url origin "$REPO_URL" 2>/dev/null || true; unset TOKEN PUSH_URL; }
trap cleanup EXIT INT TERM

# ---------- 7. Push ----------
step "Push --force"
git push -u origin "$BRANCH" --force

echo
echo -e "${G}════════════════════════════════════════════════════════${N}"
echo -e "${G}  Репозиторий очищен${N}"
echo -e "${G}════════════════════════════════════════════════════════${N}"
echo "  Проверьте: https://github.com/CAPITALOV/ChartFlow-Next"
echo "  Коммит:    $(git rev-parse --short HEAD)"
echo "  Токен удалён из .git/config"
echo