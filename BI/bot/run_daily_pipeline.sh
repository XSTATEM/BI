#!/usr/bin/env bash
# Обёртка для ежедневной рассылки (cron/systemd timer) — прогоняет весь
# пайплайн по порядку и в конце шлёт отчёт в Telegram:
#   1. pbi_to_postgres.py      — Power BI -> Postgres (сырые данные)
#   2. join_marketplaces.sql   — пересоздать вьюхи (v_marketplaces_full и т.д.)
#   3. postgres_to_gsheets.py  — Postgres -> Google Sheets (витрины для людей)
#   4. daily_sales_report.py   — Postgres -> анализ аномалий -> Telegram
#
# Важно: анализ (шаг 4) должен идти СТРОГО ПОСЛЕ обновления данных (шаги 1-3),
# иначе он проанализирует вчерашний снепшот и отчёт будет не про свежие данные.
# Скрипт останавливается на первой ошибке (set -e) — если, например, Power BI
# недоступен на шаге 1, шаги 2-4 не запустятся и вы не получите отчёт по
# неполным/старым данным молча.
#
# Настройка:
#   1. Положите .env рядом со скриптом (КЛЮЧ=значение, см. README "Переменные
#      окружения") — все переменные, нужные pbi_to_postgres.py,
#      postgres_to_gsheets.py и daily_sales_report.py разом.
#   2. chmod +x run_daily_pipeline.sh
#   3. Проверьте вручную: ./run_daily_pipeline.sh (без cron/systemd) —
#      убедитесь, что отчёт пришёл и в логе нет ошибок.
#   4. Поставьте в cron или systemd timer (см. README, раздел "Ежедневная
#      рассылка по расписанию") — на сервере, где есть сеть и до Postgres,
#      и до Power BI/Google/Telegram (Cowork-планировщик для этого не
#      подходит — нет сети до приватной БД).
#
# Логи: скрипт сам ничего не пишет в файл — перенаправляйте stdout/stderr
# при вызове (см. пример crontab в README) или смотрите journalctl, если
# запускаете через systemd timer.

set -e  # остановиться на первой ошибке — не слать отчёт по неполным данным
cd "$(dirname "$0")"

if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 1/4: Power BI -> Postgres..."
python3 pbi_to_postgres.py

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 2/4: пересоздаю вьюхи (join_marketplaces.sql)..."
psql "postgresql://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT:-5432}/${PGDATABASE}" -v ON_ERROR_STOP=1 -f join_marketplaces.sql

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 3/4: Postgres -> Google Sheets..."
python3 postgres_to_gsheets.py

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 4/4: анализ аномалий -> Telegram..."
python3 daily_sales_report.py

echo "[$(date '+%Y-%m-%d %H:%M:%S')] готово."
