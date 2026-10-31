#!/usr/bin/env bash
cd /var/www/sotis.org/data/www/pro.sotis.org

echo "=== 1. Файл на диске ==="
if grep -q "forecast/multi" main.py; then
    echo "✓ main.py содержит /api/v1/forecast/multi"
else
    echo "✗ main.py НЕ содержит /api/v1/forecast/multi — сохраните файл заново"
    exit 1
fi

echo -n "Версия в файле: "
grep -oE 'version="[0-9.]+"' main.py | head -1

echo
echo "=== 2. Перезапуск службы ==="
systemctl restart chartflow
sleep 3
systemctl is-active chartflow

echo
echo "=== 3. Версия живого API ==="
curl -s http://127.0.0.1:8000/ | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('version:', d.get('version'))
print('models:', d.get('models'))
"

echo
echo "=== 4. Тест /api/v1/forecast/multi ==="
curl -s -m 120 -X POST http://127.0.0.1:8000/api/v1/forecast/multi \
  -H "Content-Type: application/json" \
  -d '{"ticker":"SBER","horizon_days":14}' \
  -o /tmp/multi.json -w "HTTP %{http_code}  time %{time_total}s  size %{size_download}B\n"

echo
echo "Первые 500 байт ответа:"
head -c 500 /tmp/multi.json; echo