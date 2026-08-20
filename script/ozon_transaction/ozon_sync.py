#!/usr/bin/env python3
"""
ozon_sync.py — ежедневная загрузка отчётов по транзакциям Ozon → PostgreSQL

Запуск:
    python3 ozon_sync.py                        # вчерашний день (для cron)
    python3 ozon_sync.py 2026-06-01 2026-06-04  # произвольный период

Cron (каждый день в 06:00):
    0 6 * * * cd /path/to/ozon_sync && python3 ozon_sync.py >> logs/ozon_sync.log 2>&1
"""

import sys
import json
import hashlib
import logging
import time
import re
import io
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

from curl_cffi import requests
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from config import ACCOUNTS, DB_CONFIG, TABLE_NAME, OZON_URL, COOKIES_FILE, TEMP_DIR

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from telegram_bot.notifier import notify_success, notify_error  # noqa: E402

# ─── Логирование ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(Path(__file__).resolve().parent / "log_ozon_sync.txt", encoding="utf-8", mode="a+"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ─── Утилиты ──────────────────────────────────────────────────────────────────

def load_cookies() -> dict:
    """
    Загружаем cookies из файла. Поддерживает 3 формата:

    1. Словарь  {"name": "value", ...}              ← наш шаблон
    2. Список   [{"name":"n","value":"v",...}, ...]  ← экспорт EditThisCookie / Cookie-Editor
    3. Строка   "name=value; name2=value2"           ← строка из DevTools → Network → Cookie header
    """
    path = Path(COOKIES_FILE)
    if not path.exists():
        log.error(
            f"Файл cookies не найден: {COOKIES_FILE}\n"
            f"Скопируй cookies.json.example → cookies.json и заполни"
        )
        sys.exit(1)

    raw = path.read_text(encoding="utf-8").strip()

    # Формат 3: просто строка cookie-заголовка (не JSON)
    if not raw.startswith(("{", "[")):
        cookies = {}
        for part in raw.split(";"):
            part = part.strip()
            if "=" in part:
                k, _, v = part.partition("=")
                cookies[k.strip()] = v.strip()
        log.info(f"Загружено cookies из строки-заголовка: {len(cookies)} штук")
        return cookies

    data = json.loads(raw)

    # Формат 2: список объектов [{name, value, ...}]
    if isinstance(data, list):
        cookies = {
            item["name"]: item["value"]
            for item in data
            if "name" in item and "value" in item
        }
        log.info(f"Загружено cookies из списка: {len(cookies)} штук")
        return cookies

    # Формат 1: словарь {name: value}
    cookies = {k: v for k, v in data.items() if not k.startswith("_comment")}
    log.info(f"Загружено cookies из словаря: {len(cookies)} штук")
    return cookies


def normalize_column_name(name: str) -> str:
    TRANSLIT = {
        'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh',
        'з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o',
        'п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts',
        'ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu',
        'я':'ya',
    }
    name = str(name).strip().lower()
    result = ""
    for ch in name:
        result += TRANSLIT.get(ch, ch)
    result = re.sub(r"[^a-z0-9]+", "_", result)
    result = result.strip("_")
    result = re.sub(r"_+", "_", result)
    if result and result[0].isdigit():
        result = "col_" + result
    return result or "unknown"


def compute_row_hash(client_id: str, row_dict: dict) -> str:
    """MD5 от client_id + всех значений строки — для дедупликации."""
    raw = client_id + "|" + "|".join(str(v) for v in row_dict.values())
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


# ─── Скачивание ───────────────────────────────────────────────────────────────

def download_report(
    session: requests.Session,
    company_id: str,
    account_name: str,
    date_from: str,
    date_to: str,
    retries: int = 3,
) -> Optional[bytes]:
    """
    Скачиваем Excel отчёт для одного кабинета.
    Возвращает bytes файла или None при ошибке.
    """
    params  = {"date_from": date_from, "date_to": date_to}
    headers = {"x-o3-company-id": company_id}

    for attempt in range(1, retries + 1):
        try:
            log.info(
                f"  [{account_name}] Скачиваю {date_from} → {date_to} "
                f"(попытка {attempt}/{retries})"
            )
            resp = session.get(
                OZON_URL,
                params=params,
                headers=headers,
                timeout=60,
                impersonate="chrome",
            )

            # Cookies протухли
            if resp.status_code in (401, 403):
                log.error(f"Ответ Ozon: {resp.status_code} — {resp.text[:300]}")
                log.error(
                    "COOKIE_EXPIRED: Ozon вернул 403/401. "
                )
                return None

            if resp.status_code != 200:
                log.warning(f"  Статус {resp.status_code}: {resp.text[:200]}")
            else:
                ct = resp.headers.get("content-type", "")
                if "spreadsheet" in ct or "excel" in ct or "octet-stream" in ct:
                    log.info(f"  [{account_name}] Файл получен ({len(resp.content):,} байт)")
                    return resp.content
                else:
                    # Скорее всего вернулся JSON с ошибкой
                    try:
                        err = resp.json()
                        log.error(f"  Ozon вернул JSON вместо файла: {err}")
                    except Exception:
                        log.error(f"  Неожиданный content-type: {ct}\n{resp.text[:300]}")
                    return None

        except requests.exceptions.Timeout:
            log.warning(f"  Timeout (попытка {attempt})")
        except requests.exceptions.RequestException as e:
            log.warning(f"  Ошибка соединения (попытка {attempt}): {e}")

        if attempt < retries:
            wait = 2 ** attempt
            log.info(f"  Жду {wait} сек...")
            time.sleep(wait)

    log.error(f"  [{account_name}] Не удалось скачать после {retries} попыток")
    return None


# ─── Парсинг Excel ────────────────────────────────────────────────────────────

def parse_excel(content: bytes, client_id: str) -> Optional[pd.DataFrame]:
    """
    Читаем Excel, нормализуем колонки, добавляем client_id и row_hash.
    Ozon иногда добавляет несколько шапочных строк перед данными —
    ищем первую строку где есть хотя бы 3 непустых ячейки.
    """
    try:
        # Пробуем найти строку с заголовками
        raw = pd.read_excel(io.BytesIO(content), header=None)

        header_row = 0
        for i, row in raw.iterrows():
            non_empty = row.dropna().astype(str).str.strip().str.len() > 0
            if non_empty.sum() >= 3:
                header_row = i
                break

        df = pd.read_excel(io.BytesIO(content), header=header_row)

        # Убираем полностью пустые строки
        df = df.dropna(how="all")

        if df.empty:
            log.warning("  Excel файл пустой (нет данных)")
            return None

        # Нормализуем названия колонок
        original_cols = list(df.columns)
        norm_cols     = [normalize_column_name(c) for c in original_cols]

        # Если несколько колонок получили одно имя — добавляем суффикс
        seen = {}
        unique_cols = []
        for col in norm_cols:
            if col in seen:
                seen[col] += 1
                unique_cols.append(f"{col}_{seen[col]}")
            else:
                seen[col] = 0
                unique_cols.append(col)

        df.columns = unique_cols

        log.info(f"  Колонки ({len(df.columns)}): {', '.join(df.columns.tolist())}")
        log.info(f"  Строк данных: {len(df)}")

        # Добавляем мета-колонки
        df.insert(0, "client_id", client_id)
        df["row_hash"]  = df.apply(
            lambda row: compute_row_hash(client_id, row.to_dict()), axis=1
        )
        df["loaded_at"] = datetime.now()

        return df

    except Exception as e:
        log.error(f"  Ошибка парсинга Excel: {e}")
        return None


# ─── PostgreSQL ───────────────────────────────────────────────────────────────

PG_TYPE_MAP = {
    "int64":          "BIGINT",
    "int32":          "INTEGER",
    "float64":        "NUMERIC",
    "float32":        "NUMERIC",
    "bool":           "BOOLEAN",
    "datetime64[ns]": "TIMESTAMP",
    "object":         "TEXT",
}

def pg_type(dtype) -> str:
    return PG_TYPE_MAP.get(str(dtype), "TEXT")


def ensure_table(conn, df: pd.DataFrame):
    """
    Создаём таблицу если её нет.
    Если есть новые колонки — добавляем их (ALTER TABLE ADD COLUMN).
    """
    with conn.cursor() as cur:

        # Проверяем существует ли таблица
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = %s)",
            (TABLE_NAME,),
        )
        exists = cur.fetchone()[0]

        if not exists:
            # Создаём таблицу
            cols_def = []
            for col, dtype in df.dtypes.items():
                if col == "row_hash":
                    cols_def.append(f'"{col}" TEXT PRIMARY KEY')
                elif col == "loaded_at":
                    cols_def.append(f'"{col}" TIMESTAMP DEFAULT NOW()')
                else:
                    cols_def.append(f'"{col}" {pg_type(dtype)}')

            ddl = f'CREATE TABLE "{TABLE_NAME}" (\n  ' + ",\n  ".join(cols_def) + "\n);"
            log.info(f"Создаю таблицу:\n{ddl}")
            cur.execute(ddl)

            # Индекс для быстрого поиска по client_id и дате
            cur.execute(
                f'CREATE INDEX ON "{TABLE_NAME}" (client_id);'
            )
            conn.commit()
            log.info(f"Таблица {TABLE_NAME} создана.")

        else:
            # Таблица есть — добавляем новые колонки если появились
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = %s",
                (TABLE_NAME,),
            )
            existing_cols = {row[0] for row in cur.fetchall()}

            for col, dtype in df.dtypes.items():
                if col not in existing_cols:
                    pg_t = "TEXT PRIMARY KEY" if col == "row_hash" else pg_type(dtype)
                    log.info(f"Добавляю новую колонку: {col} {pg_t}")
                    cur.execute(f'ALTER TABLE "{TABLE_NAME}" ADD COLUMN IF NOT EXISTS "{col}" {pg_type(dtype)};')

            conn.commit()


def insert_rows(conn, df: pd.DataFrame) -> tuple[int, int]:
    """
    Вставляем строки с ON CONFLICT (row_hash) DO NOTHING.
    Возвращает (вставлено, пропущено дублей).
    """
    cols   = list(df.columns)
    rows   = [tuple(row) for row in df.itertuples(index=False, name=None)]
    total  = len(rows)

    # Приводим NaN → None для psycopg2
    clean_rows = []
    for row in rows:
        clean_rows.append(tuple(None if (isinstance(v, float) and v != v) else v for v in row))

    cols_quoted = ", ".join(f'"{c}"' for c in cols)
    query = (
        f'INSERT INTO "{TABLE_NAME}" ({cols_quoted}) VALUES %s '
        f'ON CONFLICT (row_hash) DO NOTHING'
    )

    with conn.cursor() as cur:
        execute_values(cur, query, clean_rows)
        inserted = cur.rowcount

    conn.commit()

    skipped = total - inserted
    return inserted, skipped


# ─── Точка входа ──────────────────────────────────────────────────────────────

def main():
    # Даты из аргументов или по умолчанию — вчера
    if len(sys.argv) == 3:
        date_from = sys.argv[1]
        date_to   = sys.argv[2]
    elif len(sys.argv) == 1:
        yesterday = datetime.now() - timedelta(days=1)
        date_from = date_to = yesterday.strftime("%Y-%m-%d")
    else:
        print("Использование: python3 ozon_sync.py [date_from date_to]")
        print("Пример:        python3 ozon_sync.py 2026-06-01 2026-06-04")
        sys.exit(1)

    log.info("=" * 60)
    log.info(f"Ozon sync: {date_from} → {date_to}")
    log.info(f"Кабинетов: {len(ACCOUNTS)}")
    log.info("=" * 60)

    # Сессия с cookies
    cookies = load_cookies()
    session = requests.Session(impersonate="chrome")
    session.cookies.update(cookies)
    session.headers.update({
        "User-Agent":        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "Accept":            "application/json, text/plain, */*",
        "Accept-Language":   "ru",
        "Referer":           "https://seller.ozon.ru/app/finances/accruals?tab=ACCRUALS_DETAILS",
        "sec-ch-ua":         '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
        "sec-ch-ua-mobile":  "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest":    "empty",
        "sec-fetch-mode":    "cors",
        "sec-fetch-site":    "same-origin",
        "x-o3-app-name":     "seller-ui",
        "x-o3-language":     "ru",
        "x-o3-page-type":    "finances-other",
    })

    # Подключение к БД
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        log.info("PostgreSQL: подключение успешно")
    except Exception as e:
        log.error(f"Не удалось подключиться к PostgreSQL: {e}")
        notify_error("ozon_sync.py", f"Не удалось подключиться к PostgreSQL: {e}")
        sys.exit(1)

    table_initialized = False  # создаём таблицу по первому датафрейму
    total_inserted = 0
    total_skipped  = 0

    for company_id, account_name in ACCOUNTS.items():
        log.info(f"\n--- {account_name} (company_id={company_id}) ---")

        content = download_report(session, company_id, account_name, date_from, date_to)
        if content is None:
            continue

        df = parse_excel(content, client_id=company_id)
        if df is None:
            continue

        # Создаём/проверяем таблицу
        try:
            ensure_table(conn, df)
            table_initialized = True
        except Exception as e:
            log.error(f"  Ошибка при создании/проверке таблицы: {e}")
            conn.rollback()
            continue

        # Вставляем
        try:
            inserted, skipped = insert_rows(conn, df)
            total_inserted += inserted
            total_skipped  += skipped
            log.info(f"  ✓ Вставлено: {inserted}, пропущено дублей: {skipped}")
        except Exception as e:
            log.error(f"  Ошибка при вставке: {e}")
            conn.rollback()

        time.sleep(1)  # пауза между кабинетами

    conn.close()

    log.info("\n" + "=" * 60)
    log.info(f"ИТОГО: вставлено {total_inserted}, пропущено {total_skipped}")
    log.info("=" * 60)

    notify_success("ozon_sync.py", f"Вставлено: {total_inserted}, пропущено дублей: {total_skipped}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception(f"Необработанная ошибка: {e}")
        notify_error("ozon_sync.py", e)
        raise
