# BI: Echips_FR — Power BI → Postgres → Google Sheets

Пайплайн выгружает аналитику по маркетплейсам (Wildberries, Ozon, Yandex Market) из модели Power BI `Echips_FR`, объединяет её в Postgres и публикует витрины в Google Sheets.

## Схема пайплайна

```
Power BI (Echips_FR)  --executeQueries-->  Postgres  --SQL VIEW-->  Postgres  --gspread-->  Google Sheets
   dax_queries.py            pbi_to_postgres.py       join_marketplaces.sql   postgres_to_gsheets.py
```

1. **`powerbi_auth.py`** — аутентификация в Power BI REST API через device code flow (MSAL). Пароль нигде не хранится; при первом запуске в консоли появится ссылка и код для входа в браузере. Токен кэшируется в `token_cache.bin`.

   Сейчас используется диагностический `CLIENT_ID` (Azure CLI) — временное решение для проверки, блокирует ли тенант `echips.ru` multi-tenant приложения (см. комментарии в файле). Для постоянной работы нужно вернуться к боевому client id.

2. **`dax_queries.py`** — DAX-запросы (`EVALUATE`/`SUMMARIZECOLUMNS`) для сырой выгрузки по каждому маркетплейсу отдельно (`raw_wb`, `raw_ozon`, `raw_yandex`), плюс справочники (`dim_sku`, `dim_calendar`, `dim_plan`). Объединение между маркетплейсами сделано не в DAX, а в Postgres — так исключаются BLANK()-заглушки под чужие колонки. Ключ соединения: `SKU (ключ)` + `Date`.

3. **`pbi_to_postgres.py`** — оркестратор: логинится через `powerbi_auth`, находит workspace `echips.ru` и датасет `Echips_FR`, выполняет запросы из `dax_queries.py` и грузит результат в Postgres (`pandas.to_sql(if_exists="replace")`, одна таблица на запрос — `fact_revenue_wb/ozon/yandex`, `dim_sku`, `dim_calendar`, `dim_plan`). Перед загрузкой дропает зависимые вьюхи (`v_marketplaces_full`, `v_marketplaces_raw_union`, `v_plan_*`), потому что Postgres не даёт пересоздать таблицы, пока вьюхи на них ссылаются.

   Подключение к Postgres — только через переменные окружения (`PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGSCHEMA`), пароль в коде не хранится.

4. **`join_marketplaces.sql`** — нужно выполнить вручную после каждого запуска `pbi_to_postgres.py`, чтобы пересоздать удалённые вьюхи поверх свежих данных:
   - `v_marketplaces_raw_union` — UNION трёх маркетплейсов в одну таблицу (аналог UNION в DAX), WB-специфичные колонки у Ozon/Yandex — NULL;
   - `v_plan_by_marketplace`, `v_plan_total` — план по направлению/неделе;
   - `v_marketplaces_full` — итоговая витрина: продажи + справочники SKU/календаря/плана.

   Известные особенности: одна и та же мера в разных выгрузках получила разный тип колонки после `pandas.to_sql` (например `"ДРР, %"` — `double precision` у WB/Yandex, но `text` у Ozon) — приведено к `text`, чтобы `UNION ALL` не падал.

5. **`history.SQL`** — отдельный, разовый скрипт (не часть регулярного пайплайна): создаёт таблицу `warehouse_stocks_history` и триггер на `public.warehouse_stocks`, который пишет туда каждое INSERT/UPDATE/DELETE. Также создаёт `v_warehouse_stocks_full` (остатки по складам: Дата, SKU, Склад, Доступно, Зарезервировано, Отгружается, Всего, Заказано) — её читает `postgres_to_gsheets.py`.

6. **`postgres_to_gsheets.py`** — читает `v_marketplaces_full` и `v_warehouse_stocks_full` из Postgres и полностью перезаписывает два листа в Google-таблице (по умолчанию `v_marketplaces_full` и `Остатки`). Аутентификация — Google Service Account, JSON-ключ хранится вне репозитория, путь передаётся через `GOOGLE_SERVICE_ACCOUNT_FILE`.

7. **`Справочник артикулов.xlsx`** — справочник SKU/артикулов (источник для `dim_sku` в модели Power BI).

8. **`daily_sales_report.py`** — отдельный от основного пайплайна скрипт: читает `v_marketplaces_full` и `v_warehouse_stocks_full` из Postgres, правилами/порогами находит аномалии (просадки/скачки выручки по направлению и по SKU, скачки ДРР, критичные остатки на складе, низкий "Запас, дни", отставание от плана недели), собирает текст отчёта (через Claude API, с резервным шаблоном без LLM, если ключ не задан) и отправляет его в Telegram-бота. Не изменяет данные в Postgres, только читает. Логика поиска аномалий и сборки текста вынесена в `build_report_text()` — переиспользуется в `telegram_bot.py`. Подробности — в докстринге файла.

9. **`telegram_bot.py`** — тот же анализ, что в `daily_sales_report.py`, но по запросу: постоянно работающий процесс, слушает сообщения боту (long polling) и присылает отчёт в ответ, в тот же чат. Не требует `TELEGRAM_CHAT_ID` заранее. Подробности — в докстринге файла.

## Порядок запуска

```
python pbi_to_postgres.py          # 1. Power BI -> Postgres
# затем выполнить вручную:
psql ... -f join_marketplaces.sql  # 2. пересоздать вьюхи
python postgres_to_gsheets.py      # 3. Postgres -> Google Sheets
python daily_sales_report.py       # 4a. Postgres -> анализ аномалий -> Telegram, push по cron (опционально, независимо от шага 3)
python telegram_bot.py             # 4b. или: постоянно работающий бот, отвечает по запросу (альтернатива 4a)
```

`history.SQL` выполняется один раз при настройке (или при изменении структуры `warehouse_stocks`), в обычный пайплайн не входит.

## Ежедневный отчёт для продажников (`daily_sales_report.py`, `telegram_bot.py`)

Логика поиска аномалий и сборки текста отчёта общая (`build_report_text()` в
`daily_sales_report.py`) — есть два способа её получить:

- **`daily_sales_report.py`** — разовый запуск, шлёт отчёт в заранее заданный
  `TELEGRAM_CHAT_ID` (push по расписанию, через `cron`).
- **`telegram_bot.py`** — постоянно работающий процесс: слушает сообщения и
  присылает отчёт в ответ на запрос (`/report` или любой текст), в тот чат,
  откуда написали. `TELEGRAM_CHAT_ID` заранее не нужен — берётся из
  входящего сообщения.

Настройка (общая для обоих):

1. Создать Telegram-бота через `@BotFather` (`/newbot`) — получите `TELEGRAM_BOT_TOKEN`.
2. (Опционально, для текста через LLM вместо простого шаблона) получить ключ Claude API — `ANTHROPIC_API_KEY`. Если для оплаты используется сторонний прокси-эндпоинт (например, биллинг-прокладка для РФ) — укажите его в `ANTHROPIC_BASE_URL`; в этом случае агрегированные находки (не сырые данные о продажах) идут через этот сторонний сервис, а не напрямую в Anthropic — учитывайте при выборе провайдера.
3. Убедиться, что данные в Postgres свежие (пайплайн `pbi_to_postgres.py` + `join_marketplaces.sql` уже отработал).

Для `daily_sales_report.py` (push по расписанию) — дополнительно:

4. Добавить бота в чат/канал, куда должен приходить отчёт, и написать боту любое сообщение.
5. Открыть `https://api.telegram.org/bot<TOKEN>/getUpdates` в браузере, найти `"chat":{"id": ...}` — это `TELEGRAM_CHAT_ID`.
6. Запускать раз в день через `cron` на сервере, где есть сетевой доступ и к Postgres, и в интернет (например, на том же сервере, где стоит Postgres) — Cowork-планировщик для этого не подходит: у него нет сети до приватной БД и до Telegram API. Обратите внимание: сам `daily_sales_report.py` только читает уже загруженные данные — чтобы отчёт был про свежие данные, перед ним должен успеть отработать весь пайплайн (`pbi_to_postgres.py` + `join_marketplaces.sql` + `postgres_to_gsheets.py`). Готовая обёртка, которая прогоняет всё по порядку одной командой — `run_daily_pipeline.sh`, см. раздел "Ежедневная рассылка по расписанию" ниже.

Для `telegram_bot.py` (по запросу) — дополнительно:

4. Задать `TELEGRAM_ALLOWED_CHAT_IDS` (через запятую) — список chat_id, которым бот разрешает отвечать. Без этой переменной бот отвечает любому, кто ему напишет, что нежелательно для данных о продажах.
5. Запустить процесс на сервере с доступом к Postgres и в интернет и оставить работать постоянно (не через cron — это долгоживущий процесс). Проще всего — как systemd-сервис, чтобы автоматически перезапускался при падении/перезагрузке сервера:

   ```ini
   # /etc/systemd/system/sales-telegram-bot.service
   [Unit]
   Description=Sales anomaly Telegram bot
   After=network.target postgresql.service

   [Service]
   WorkingDirectory=/path/to/BI
   EnvironmentFile=/path/to/BI/.env
   ExecStart=/usr/bin/python3 telegram_bot.py
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

   ```
   sudo systemctl daemon-reload
   sudo systemctl enable --now sales-telegram-bot
   sudo systemctl status sales-telegram-bot   # проверить, что запустился
   journalctl -u sales-telegram-bot -f        # логи в реальном времени
   ```

   `.env` — обычный файл `КЛЮЧ=значение` (см. таблицу переменных ниже), не должен попадать в git.

Все пороги аномалий (% отклонения выручки, скачок ДРР, критичный остаток и т.д.) настраиваются через переменные окружения — см. докстринг `daily_sales_report.py`, значения по умолчанию разумны для старта и их можно будет поднастроить по факту первых отчётов.

## Ежедневная рассылка по расписанию (`run_daily_pipeline.sh`)

`daily_sales_report.py` сам по себе только читает `v_marketplaces_full` — чтобы
отчёт был про свежие данные, перед ним нужно прогнать весь пайплайн
(`pbi_to_postgres.py` -> `join_marketplaces.sql` -> `postgres_to_gsheets.py`).
`run_daily_pipeline.sh` делает это одной командой и останавливается на первой
ошибке (`set -e`), чтобы не прислать отчёт по неполным/старым данным молча.

Настройка (на сервере, где есть сеть и до Postgres, и до Power BI/Google/
Telegram — Cowork-планировщик для этого не подходит, у него нет сети до
приватной БД):

1. `chmod +x run_daily_pipeline.sh`.
2. Положить `.env` рядом со скриптом (см. таблицу переменных ниже) — включая
   `PGHOST`/`PGPORT`/`PGDATABASE`/`PGUSER`/`PGPASSWORD`, `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID` (см. пункты 4-5 раздела выше, как его узнать) и,
   опционально, `ANTHROPIC_API_KEY`.
3. Убедиться, что в `PATH` есть `psql` (клиент Postgres) — скрипт использует
   его для `join_marketplaces.sql`.
4. Проверить вручную: `./run_daily_pipeline.sh` — отчёт должен прийти в
   Telegram, в выводе не должно быть ошибок.

Дальше — на выбор, cron или systemd timer:

**Вариант A — cron** (проще, если сервер и так только под cron-задачи):

```
crontab -e
```

```cron
# Ежедневно в 08:00 — на этот момент данные маркетплейсов за вчера уже должны
# быть готовы (сам пайплайн проверяет доступность Power BI и падает с ошибкой,
# если данных ещё нет — тогда просто ничего не придёт, посмотрите в лог).
0 8 * * * /path/to/BI/run_daily_pipeline.sh >> /var/log/bi_daily_pipeline.log 2>&1
```

Проверить, что запись реально сработала:

```
tail -f /var/log/bi_daily_pipeline.log
```

**Вариант B — systemd timer** (лучше видно статус/историю запусков через
`systemctl`/`journalctl`, тот же стиль, что и unit для `telegram_bot.py` выше):

```ini
# /etc/systemd/system/bi-daily-pipeline.service
[Unit]
Description=BI daily pipeline + Telegram digest
After=network.target postgresql.service

[Service]
Type=oneshot
WorkingDirectory=/path/to/BI
ExecStart=/path/to/BI/run_daily_pipeline.sh
```

```ini
# /etc/systemd/system/bi-daily-pipeline.timer
[Unit]
Description=Запускать bi-daily-pipeline.service ежедневно в 08:00

[Timer]
OnCalendar=*-*-* 08:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```
sudo systemctl daemon-reload
sudo systemctl enable --now bi-daily-pipeline.timer
systemctl list-timers bi-daily-pipeline.timer   # когда следующий запуск
journalctl -u bi-daily-pipeline.service -f       # логи в реальном времени
```

`Persistent=true` — если сервер был выключен в 08:00, таймер досрочно
запустит пропущенный прогон при следующей загрузке, а не будет ждать до
следующего дня.

## Переменные окружения

| Переменная | Скрипт | Назначение |
|---|---|---|
| `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGSCHEMA` | `pbi_to_postgres.py`, `postgres_to_gsheets.py`, `daily_sales_report.py` | подключение к Postgres (`PGPORT` по умолчанию 5432, `PGSCHEMA` — `public`) |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | `postgres_to_gsheets.py` | путь к JSON-ключу сервисного аккаунта Google |
| `GSHEET_ID` | `postgres_to_gsheets.py` | id целевой Google-таблицы |
| `GSHEET_TAB` (по умолчанию `v_marketplaces_full`), `GSHEET_STOCK_TAB` (по умолчанию `Остатки`) | `postgres_to_gsheets.py` | имена листов назначения |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | `daily_sales_report.py` | токен бота (`@BotFather`) и id чата/канала для отправки отчёта |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS` (опц., через запятую) | `telegram_bot.py` | токен бота; список разрешённых chat_id — без него бот отвечает любому написавшему |
| `ANTHROPIC_API_KEY` (опц.), `ANTHROPIC_MODEL` (по умолчанию `claude-sonnet-5`), `ANTHROPIC_BASE_URL` (опц.) | `daily_sales_report.py` | текст отчёта через Claude; без ключа — резервный шаблон без LLM. `ANTHROPIC_BASE_URL` — переопределить эндпоинт (например, прокси-биллинг для РФ) |
| `ANOMALY_LOOKBACK_DAYS`, `ANOMALY_PCT_THRESHOLD`, `ANOMALY_Z_THRESHOLD`, `MIN_REVENUE_FOR_CHECK`, `DRR_PP_THRESHOLD`, `STOCK_LOW_QTY`, `STOCK_LOW_DAYS`, `PLAN_PACE_THRESHOLD_PCT` | `daily_sales_report.py` | пороги детекторов аномалий, у всех есть значения по умолчанию (см. докстринг файла) |

Секреты (пароли, ключи) нигде не хранятся в коде — только в переменных окружения / отдельных файлах вне репозитория.

## Зависимости

См. `requirements.txt`: `msal`, `requests`, `pandas`, `SQLAlchemy`, `psycopg2-binary`, `gspread`, `google-auth`.

```
pip install -r requirements.txt
```
