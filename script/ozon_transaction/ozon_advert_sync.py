#!/usr/bin/env python3
"""
ozon_advert_sync.py — загрузка статистики рекламы Ozon (по SKU) через куки → PostgreSQL

Запуск:
    python3 ozon_advert_sync.py                        # последние 7 дней
    python3 ozon_advert_sync.py 2026-06-01 2026-06-10  # произвольный период

Cron (каждый день в 07:00):
    0 7 * * * cd /path/to/ozon_sync && python3 ozon_advert_sync.py >> logs/ozon_advert.log 2>&1

Перед первым запуском:
    1. Открой seller.ozon.ru → Продвижение → Аналитика продвижения
    2. Открой DevTools → Network → найди запрос к sku_statistics
    3. Скопируй cookies в cookies.json (тот же файл что и для ozon_sync.py)
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

from config import ACCOUNTS, DB_CONFIG, COOKIES_FILE

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from telegram_bot.notifier import notify_success, notify_error  # noqa: E402

# ─── Настройки ────────────────────────────────────────────────────────────────
TABLE_NAME = "ozon_advert_cookie"

ADVERT_URL = (
    "https://seller.ozon.ru/performance-api/seller-api"
    "/adv-performance-adrev/adrev/v1/reports/sku_statistics"
)

# ─── Логирование ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(Path(__file__).resolve().parent / "log_ozon_advert_sync.txt", encoding="utf-8", mode="a+"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ─── Утилиты (из ozon_sync.py) ───────────────────────────────────────────────

def load_cookies() -> dict:
    path = Path(COOKIES_FILE)
    if not path.exists():
        log.error(f"Файл cookies не найден: {COOKIES_FILE}")
        sys.exit(1)

    raw = path.read_text(encoding="utf-8").strip()

    if not raw.startswith(("{", "[")):
        cookies = {}
        for part in raw.split(";"):
            part = part.strip()
            if "=" in part:
                k, _, v = part.partition("=")
                cookies[k.strip()] = v.strip()
        log.info(f"Загружено cookies: {len(cookies)} штук")
        return cookies

    data = json.loads(raw)

    if isinstance(data, list):
        cookies = {item["name"]: item["value"] for item in data if "name" in item and "value" in item}
        log.info(f"Загружено cookies из списка: {len(cookies)} штук")
        return cookies

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
    raw = client_id + "|" + "|".join(str(v) for v in row_dict.values())
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


# ─── Скачивание ───────────────────────────────────────────────────────────────

def download_advert_report(
    session: requests.Session,
    company_id: str,
    account_name: str,
    date_from: str,
    date_to: str,
    retries: int = 3,
) -> Optional[dict]:
    """
    Запрашиваем статистику рекламы по SKU.
    Возвращает JSON-ответ или None.
    """
    headers = {
        "x-o3-company-id": company_id,
        "Content-Type": "application/json",
    }

    body = {
        "timeBounds": {
            "from": date_from,
            "to": date_to,
        },
        "reportFormat": "XLSX",
    }

    for attempt in range(1, retries + 1):
        try:
            log.info(
                f"  [{account_name}] Запрашиваю {date_from} → {date_to} "
                f"(попытка {attempt}/{retries})"
            )
            resp = session.post(
                ADVERT_URL,
                json=body,
                headers=headers,
                timeout=120,
                impersonate="chrome",
            )

            if resp.status_code in (401, 403):
                log.error(f"  Ответ: {resp.status_code} — cookies протухли")
                return None

            if resp.status_code != 200:
                log.warning(f"  Статус {resp.status_code}: {resp.text[:300]}")
            else:
                ct = resp.headers.get("content-type", "")

                # Если пришёл Excel
                if "spreadsheet" in ct or "excel" in ct or "octet-stream" in ct:
                    log.info(f"  [{account_name}] Excel получен ({len(resp.content):,} байт)")
                    return {"type": "excel", "content": resp.content}

                # Если пришёл JSON
                if "json" in ct:
                    data = resp.json()
                    if isinstance(data, dict) and data.get("error"):
                        log.error(f"  Ошибка API: {data['error']}")
                        return None
                    log.info(f"  [{account_name}] JSON получен")
                    return {"type": "json", "content": data}

                # Попробуем как JSON
                try:
                    data = resp.json()
                    log.info(f"  [{account_name}] Ответ получен (JSON)")
                    return {"type": "json", "content": data}
                except Exception:
                    log.error(f"  Неожиданный content-type: {ct}")
                    return None

        except requests.exceptions.Timeout:
            log.warning(f"  Timeout (попытка {attempt})")
        except requests.exceptions.RequestException as e:
            log.warning(f"  Ошибка соединения (попытка {attempt}): {e}")

        if attempt < retries:
            wait = 2 ** attempt
            time.sleep(wait)

    log.error(f"  [{account_name}] Не удалось получить данные после {retries} попыток")
    return None


# ─── Парсинг ──────────────────────────────────────────────────────────────────

def parse_response(response: dict, client_id: str) -> Optional[pd.DataFrame]:
    """Парсим ответ — Excel или JSON — в DataFrame."""

    if response["type"] == "excel":
        return parse_excel(response["content"], client_id)

    elif response["type"] == "json":
        return parse_json(response["content"], client_id)

    return None


def parse_excel(content: bytes, client_id: str) -> Optional[pd.DataFrame]:
    """Парсим Excel-файл (как в ozon_sync.py)."""
    try:
        raw = pd.read_excel(io.BytesIO(content), header=None)

        header_row = 0
        for i, row in raw.iterrows():
            non_empty = row.dropna().astype(str).str.strip().str.len() > 0
            if non_empty.sum() >= 3:
                header_row = i
                break

        df = pd.read_excel(io.BytesIO(content), header=header_row)
        df = df.dropna(how="all")

        if df.empty:
            log.warning("  Excel пустой")
            return None

        df.columns = [normalize_column_name(c) for c in df.columns]

        # Дедупликация имён столбцов
        seen = {}
        unique_cols = []
        for col in df.columns:
            if col in seen:
                seen[col] += 1
                unique_cols.append(f"{col}_{seen[col]}")
            else:
                seen[col] = 0
                unique_cols.append(col)
        df.columns = unique_cols

        # Заменяем "-" на None (Ozon пишет "-" вместо 0 когда нет данных)
        for col in df.columns:
            if df[col].dtype == object:
                mask = df[col].astype(str).str.strip() == "-"
                if mask.any():
                    df[col] = df[col].where(~mask, other=None)
                    try:
                        converted = pd.to_numeric(df[col], errors="coerce")
                        if converted.notna().sum() > 0:
                            df[col] = converted
                    except Exception:
                        pass

        df.insert(0, "client_id", client_id)
        df["row_hash"] = df.apply(lambda row: compute_row_hash(client_id, row.to_dict()), axis=1)
        df["loaded_at"] = datetime.now()

        log.info(f"  Колонки: {', '.join(df.columns.tolist())}")
        log.info(f"  Строк: {len(df)}")
        return df

    except Exception as e:
        log.error(f"  Ошибка парсинга Excel: {e}")
        return None


def parse_json(data: dict, client_id: str) -> Optional[pd.DataFrame]:
    """Парсим JSON-ответ в DataFrame."""
    try:
        # Ищем массив данных в ответе
        rows = None
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            # Типичные ключи где лежат данные
            for key in ["data", "rows", "items", "result", "statistics"]:
                if key in data and isinstance(data[key], list):
                    rows = data[key]
                    break

        if not rows:
            log.warning(f"  Не нашёл массив данных в JSON. Ключи: {list(data.keys()) if isinstance(data, dict) else 'list'}")
            # Сохраняем для отладки
            Path("/tmp/ozon_advert_debug.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2)[:10000]
            )
            log.info("  JSON сохранён в /tmp/ozon_advert_debug.json для отладки")
            return None

        df = pd.json_normalize(rows)

        if df.empty:
            log.warning("  JSON пустой")
            return None

        df.columns = [normalize_column_name(c) for c in df.columns]

        df.insert(0, "client_id", client_id)
        df["row_hash"] = df.apply(lambda row: compute_row_hash(client_id, row.to_dict()), axis=1)
        df["loaded_at"] = datetime.now()

        log.info(f"  Колонки: {', '.join(df.columns.tolist())}")
        log.info(f"  Строк: {len(df)}")
        return df

    except Exception as e:
        log.error(f"  Ошибка парсинга JSON: {e}")
        return None


# ─── PostgreSQL ───────────────────────────────────────────────────────────────

PG_TYPE_MAP = {
    "int64": "BIGINT", "int32": "INTEGER",
    "float64": "NUMERIC", "float32": "NUMERIC",
    "bool": "BOOLEAN", "datetime64[ns]": "TIMESTAMP",
    "object": "TEXT",
}

def pg_type(dtype) -> str:
    return PG_TYPE_MAP.get(str(dtype), "TEXT")


def ensure_table(conn, df: pd.DataFrame):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
            (TABLE_NAME,),
        )
        exists = cur.fetchone()[0]

        if not exists:
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
            cur.execute(f'CREATE INDEX ON "{TABLE_NAME}" (client_id);')
            conn.commit()
            log.info(f"Таблица {TABLE_NAME} создана.")
        else:
            cur.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                (TABLE_NAME,),
            )
            existing_cols = {row[0] for row in cur.fetchall()}

            for col, dtype in df.dtypes.items():
                if col not in existing_cols:
                    log.info(f"Добавляю колонку: {col} {pg_type(dtype)}")
                    cur.execute(
                        f'ALTER TABLE "{TABLE_NAME}" ADD COLUMN IF NOT EXISTS "{col}" {pg_type(dtype)};'
                    )
            conn.commit()


def insert_rows(conn, df: pd.DataFrame) -> tuple:
    cols = list(df.columns)
    rows = [tuple(row) for row in df.itertuples(index=False, name=None)]

    clean_rows = []
    for row in rows:
        clean_rows.append(
            tuple(None if (isinstance(v, float) and v != v) else v for v in row)
        )

    cols_quoted = ", ".join(f'"{c}"' for c in cols)
    query = (
        f'INSERT INTO "{TABLE_NAME}" ({cols_quoted}) VALUES %s '
        f'ON CONFLICT (row_hash) DO NOTHING'
    )

    with conn.cursor() as cur:
        execute_values(cur, query, clean_rows)
        inserted = cur.rowcount

    conn.commit()
    skipped = len(rows) - inserted
    return inserted, skipped


# ─── Точка входа ──────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) == 3:
        date_from = sys.argv[1]
        date_to = sys.argv[2]
    elif len(sys.argv) == 1:
        date_to = datetime.now().strftime("%Y-%m-%d")
        date_from = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    else:
        print("Использование: python3 ozon_advert_sync.py [date_from date_to]")
        print("Пример:        python3 ozon_advert_sync.py 2026-06-01 2026-06-10")
        sys.exit(1)

    log.info("=" * 60)
    log.info(f"Ozon Advert sync: {date_from} → {date_to}")
    log.info(f"Кабинетов: {len(ACCOUNTS)}")
    log.info("=" * 60)

    cookies = load_cookies()
    session = requests.Session(impersonate="chrome")
    session.cookies.update(cookies)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru",
        "Referer": "https://seller.ozon.ru/product/overview",
        "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-o3-app-name": "seller-ui",
        "x-o3-language": "ru",
        "x-o3-page-type": "promotion-analytics",
    })

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        log.info("PostgreSQL: подключение успешно")
    except Exception as e:
        log.error(f"Не удалось подключиться к PostgreSQL: {e}")
        notify_error("ozon_advert_sync.py", f"Не удалось подключиться к PostgreSQL: {e}")
        sys.exit(1)

    total_inserted = 0
    total_skipped = 0

    # Генерируем список дат
    d_from = datetime.strptime(date_from, "%Y-%m-%d")
    d_to = datetime.strptime(date_to, "%Y-%m-%d")
    dates = []
    d = d_from
    while d <= d_to:
        dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)

    log.info(f"Дней для загрузки: {len(dates)}")

    for company_id, account_name in ACCOUNTS.items():
        log.info(f"\n--- {account_name} (company_id={company_id}) ---")

        for day in dates:
            response = download_advert_report(
                session, company_id, account_name, day, day
            )
            if response is None:
                continue

            df = parse_response(response, client_id=company_id)
            if df is None:
                continue

            # Добавляем дату из параметров запроса
            df.insert(1, "date", day)

            try:
                ensure_table(conn, df)
            except Exception as e:
                log.error(f"  Ошибка таблицы: {e}")
                conn.rollback()
                continue

            try:
                inserted, skipped = insert_rows(conn, df)
                total_inserted += inserted
                total_skipped += skipped
                log.info(f"  [{day}] ✓ Вставлено: {inserted}, пропущено: {skipped}")
            except Exception as e:
                log.error(f"  [{day}] Ошибка вставки: {e}")
                conn.rollback()

            time.sleep(1)

        time.sleep(2)

    conn.close()

    log.info("\n" + "=" * 60)
    log.info(f"ИТОГО: вставлено {total_inserted}, пропущено {total_skipped}")
    log.info("=" * 60)

    notify_success("ozon_advert_sync.py", f"Вставлено: {total_inserted}, пропущено дублей: {total_skipped}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception(f"Необработанная ошибка: {e}")
        notify_error("ozon_advert_sync.py", e)
        raise