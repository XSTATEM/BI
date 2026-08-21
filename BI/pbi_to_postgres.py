"""
Пайплайн: Power BI Service (Echips_FR) -> pandas -> Postgres.

Шаги:
  1. Аутентификация через device code flow (powerbi_auth.py) — без пароля в коде.
  2. Поиск workspace "echips.ru" и датасета Echips_FR в нём (Groups/Datasets REST API).
  3. Выполнение DAX-запросов (dax_queries.py) через executeQueries.
  4. Дроп вьюх v_marketplaces_full/v_marketplaces_raw_union (иначе Postgres
     не даёт пересоздать таблицы, от которых они зависят) и загрузка
     результатов в Postgres (одна таблица на запрос, if_exists="replace").

После этого скрипта нужно заново выполнить, В ТАКОМ ПОРЯДКЕ:
  1. history.SQL             — пересоздаёт v_warehouse_stocks_fbs,
                                v_stocks_all_total и др. (разделы 5-6).
  2. join_marketplaces.sql    — пересоздаёт v_marketplaces_raw_union/
                                v_marketplaces_full поверх свежих данных.
ПОРЯДОК ВАЖЕН: v_marketplaces_raw_union читает v_warehouse_stocks_fbs и
v_stocks_all_total из history.SQL — если запустить join_marketplaces.sql
раньше history.SQL, он упадёт с "relation ... does not exist".

--------------------------------------------------------------------------
ИСПРАВЛЕНО 18.08.2026 — ТИХАЯ ОБРЕЗКА ОТВЕТА executeQueries
--------------------------------------------------------------------------
У executeQueries есть лимит на размер ответа — 15 728 640 байт (15 МиБ).
При его превышении API возвращает HTTP 200, отдаёт ЧАСТИЧНЫЙ набор строк и
кладёт описание ошибки ВНУТРЬ тела ответа:

    results[0]["error"] = {"code": "DaxByteCountNotSupported", ...}

Прежняя версия проверяла только resp.status_code, поэтому обрезанные данные
молча доезжали до Postgres и затирали хорошие через if_exists="replace".
По Ozon это превратило 19 796 строк за 90 дней в 12 298 строк с 03.08, а
выручку — со 117 992 349 руб в 3 877 406 руб. Расхождение всплыло только
при ручной сверке отчёта.

Размер раздувает сочетание includeNulls=True и кириллических имён колонок:
null пишется вместе с полным именем колонки, а кириллица в JSON экранируется
как \\uXXXX (6 байт на символ). На плотном ценовом блоке Ozon (с 03.08 ~892
строки в день, где заполнена почти только "Цена в ЛК") это ~1 300 байт на
строку почти без полезных данных.

Что теперь делается:
  1. Наличие поля "error" в ответе — это ошибка, скрипт падает.
  2. Запросы с 90-дневным окном выполняются по чанкам: литерал
     DATESINPERIOD('Календарь'[Date], TODAY(), -90, DAY) подменяется на
     DATESBETWEEN с границами чанка, результаты склеиваются. Не влезший
     чанк делится пополам рекурсивно.
  3. Перед записью в Postgres — санити-чек по числу строк и минимальной дате.

includeNulls=True оставлен НАМЕРЕННО: без него полностью пустая колонка
исчезает из ответа, и join_marketplaces.sql падает с "column does not exist".
--------------------------------------------------------------------------

Все параметры подключения к Postgres и пароль берутся ТОЛЬКО из переменных
окружения — ничего не хардкодится и не передаётся через чат:

    PGHOST      — хост Postgres
    PGPORT      — порт (по умолчанию 5432)
    PGDATABASE  — имя базы
    PGUSER      — пользователь
    PGPASSWORD  — пароль (обязательно через env var, не в коде)
    PGSCHEMA    — схема (по умолчанию "public")

Запуск:
    PGHOST=... PGPORT=... PGDATABASE=... PGUSER=... PGPASSWORD=... \
        python pbi_to_postgres.py
"""

import datetime as dt
import os
import sys

import pandas as pd
import requests
from sqlalchemy import create_engine, text

from powerbi_auth import get_access_token
from dax_queries import QUERIES

# Вьюхи из join_marketplaces.sql и history.SQL (разделы 5-6) зависят от таблиц
# fact_revenue_*/dim_*/transfer_items, поэтому pandas.to_sql(if_exists="replace")
# не может их DROP+CREATE, пока вьюхи существуют (DependentObjectsStillExist).
DEPENDENT_VIEWS = [
    "v_marketplaces_full",
    "v_plan_by_marketplace",
    "v_plan_total",
    "v_plan_pivot",  # старое имя вьюхи, дропаем на случай если ещё осталась с прошлого запуска
    "v_marketplaces_raw_union",
    "v_stocks_all_total",       # history.SQL, раздел 6 — зависит от fact_revenue_wb/ozon/yandex
    "v_stocks_by_marketplace",  # history.SQL, раздел 6 — зависит от fact_revenue_wb/ozon/yandex
    "v_warehouse_stocks_fbs",              # history.SQL, раздел 5 — зависит от transfer_items
    "v_transfer_items_by_sku_warehouse",   # history.SQL, раздел 5 — зависит от transfer_items
    "v_cost_per_sku",           # history.SQL, раздел 4.5 — зависит от dim_sku И dim_cost_price,
                                # обе таблицы ниже перезаписываются if_exists="replace"
]

WORKSPACE_NAME = "echips.ru"
DATASET_NAME = "Echips_FR"
PBI_API = "https://api.powerbi.com/v1.0/myorg"

# Таблицы, в которые грузим каждый запрос
TARGET_TABLES = {
    "raw_wb": "fact_revenue_wb",
    "raw_ozon": "fact_revenue_ozon",
    "raw_yandex": "fact_revenue_yandex",
    "dim_sku": "dim_sku",
    "dim_calendar": "dim_calendar",
    "dim_plan": "dim_plan",
    "dim_cost_price": "dim_cost_price",
    "raw_transfer_items": "transfer_items",
    "raw_transit_receivables": "fact_transit_receivables",
    "raw_ozon_other": "fact_ozon_other_deductions",
}

# --- Нарезка по датам -------------------------------------------------------

# Литерал окна, одинаковый в raw_wb / raw_ozon / raw_yandex / raw_ozon_other.
# ВАЖНО: если в dax_queries.py поменять текст этой строки (пробелы, регистр,
# число дней) — подмена перестанет срабатывать, и запрос снова пойдёт одним
# куском. Тогда правь литерал и здесь.
PERIOD_LITERAL = "DATESINPERIOD('Календарь'[Date], TODAY(), -90, DAY)"

PERIOD_DAYS = 90

# Стартовый размер чанка в днях. Плотные ценовые блоки дают ~900 строк в день,
# то есть 15 дней ~ 8 МиБ при 29 колонках. Не влезший чанк делится пополам
# автоматически, поэтому значение можно не подбирать вручную.
CHUNK_DAYS = 15

BYTE_LIMIT_CODES = {"DaxByteCountNotSupported", "ResultSetTooLarge"}

# Минимальное ожидаемое число строк — грубая защита от схлопнувшейся выгрузки.
# Ниже порога скрипт падает, НЕ записывая в Postgres. Подстрой под свои объёмы.
MIN_ROWS = {
    "raw_wb": 4000,
    "raw_ozon": 15000,
    "raw_yandex": 1200,
    "raw_ozon_other": 800,
}


class DaxTooLarge(RuntimeError):
    """Ответ executeQueries превысил лимит в 15 МиБ."""


def get_workspace_id(token: str, workspace_name: str) -> str:
    resp = requests.get(
        f"{PBI_API}/groups",
        headers={"Authorization": f"Bearer {token}"},
        params={"$filter": f"name eq '{workspace_name}'"},
        timeout=30,
    )
    resp.raise_for_status()
    values = resp.json().get("value", [])
    if not values:
        raise RuntimeError(f"Воркспейс '{workspace_name}' не найден (или нет доступа).")
    return values[0]["id"]


def get_dataset_id(token: str, group_id: str) -> str:
    resp = requests.get(
        f"{PBI_API}/groups/{group_id}/datasets",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    values = resp.json().get("value", [])
    if not values:
        raise RuntimeError("В воркспейсе нет датасетов.")

    for ds in values:
        if ds.get("name") == DATASET_NAME:
            return ds["id"]

    if len(values) == 1:
        # Раньше здесь молча возвращался единственный датасет без проверки
        # имени — если бы в воркспейсе лежал не тот датасет, пайплайн увёл бы
        # чужие данные без единого предупреждения. Теперь хотя бы говорим вслух.
        print(f"    ВНИМАНИЕ: датасета '{DATASET_NAME}' нет, "
              f"использую единственный доступный: {values[0].get('name')!r}")
        return values[0]["id"]

    names = [d.get("name") for d in values]
    raise RuntimeError(
        f"В воркспейсе несколько датасетов и среди них нет '{DATASET_NAME}': {names}."
    )


def _dax_date(d: dt.date) -> str:
    return f"DATE({d.year},{d.month},{d.day})"


def _with_window(dax: str, start: dt.date, end: dt.date) -> str:
    """Подменяет 90-дневное окно на явный диапазон DATESBETWEEN."""
    replacement = (
        f"DATESBETWEEN('Календарь'[Date], {_dax_date(start)}, {_dax_date(end)})"
    )
    return dax.replace(PERIOD_LITERAL, replacement)


def run_dax_query(token: str, group_id: str, dataset_id: str, dax: str) -> pd.DataFrame:
    """Выполняет один DAX-запрос. Падает, если ответ обрезан."""
    url = f"{PBI_API}/groups/{group_id}/datasets/{dataset_id}/executeQueries"
    payload = {
        "queries": [{"query": dax}],
        "serializerSettings": {"includeNulls": True},
    }
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=300,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"executeQueries failed [{resp.status_code}]: {resp.text}")

    result = resp.json()["results"][0]

    # ГЛАВНОЕ: при обрезке API отдаёт HTTP 200 + частичные строки + error.
    err = result.get("error")
    if err:
        code = (err or {}).get("code", "")
        msg = (err or {}).get("message", err)
        if code in BYTE_LIMIT_CODES or "bytes" in str(msg).lower():
            raise DaxTooLarge(f"{code}: {msg}")
        raise RuntimeError(f"executeQueries вернул ошибку в теле ответа: {err}")

    rows = result["tables"][0]["rows"]
    df = pd.DataFrame(rows)
    # DAX возвращает имена колонок вида "TableName[Column Name]" или "[Measure Name]" —
    # чистим до последней части в квадратных скобках.
    df.columns = [c.split("[")[-1].rstrip("]") if "[" in c else c for c in df.columns]
    return df


def _run_range(token, group_id, dataset_id, dax, start, end, depth=0):
    """Выполняет запрос на диапазоне дат, деля его пополам при превышении лимита."""
    indent = "       " + "  " * depth
    try:
        df = run_dax_query(token, group_id, dataset_id, _with_window(dax, start, end))
        print(f"{indent}{start}..{end}: {len(df)} строк")
        return [df]
    except DaxTooLarge:
        if start >= end:
            raise RuntimeError(
                f"Один день ({start}) не влезает в лимит 15 МиБ — "
                "нужно сокращать число колонок в запросе."
            )
        mid = start + (end - start) // 2
        print(f"{indent}{start}..{end}: не влезло в 15 МиБ, делю пополам")
        return (_run_range(token, group_id, dataset_id, dax, start, mid, depth + 1)
                + _run_range(token, group_id, dataset_id, dax,
                             mid + dt.timedelta(days=1), end, depth + 1))


def run_dax_windowed(token, group_id, dataset_id, dax, query_key=""):
    """Выполняет запрос целиком или по чанкам, если в нём есть 90-дневное окно."""
    if PERIOD_LITERAL not in dax:
        return run_dax_query(token, group_id, dataset_id, dax)

    today = dt.date.today()
    first = today - dt.timedelta(days=PERIOD_DAYS - 1)

    parts = []
    cursor = first
    while cursor <= today:
        chunk_end = min(cursor + dt.timedelta(days=CHUNK_DAYS - 1), today)
        parts.extend(_run_range(token, group_id, dataset_id, dax, cursor, chunk_end))
        cursor = chunk_end + dt.timedelta(days=1)

    df = pd.concat(parts, ignore_index=True)

    # --- Санити-чек ДО записи в Postgres ---
    minimum = MIN_ROWS.get(query_key)
    if minimum and len(df) < minimum:
        raise RuntimeError(
            f"{query_key}: получено {len(df)} строк, ожидалось не меньше {minimum}. "
            "Похоже на обрезку или сбой источника — запись в Postgres отменена."
        )

    datecol = next((c for c in df.columns if c.lower() == "date"), None)
    if datecol is not None and len(df):
        dmin = pd.to_datetime(df[datecol], errors="coerce", format="mixed").min()
        if pd.notna(dmin) and dmin.date() > first + dt.timedelta(days=5):
            raise RuntimeError(
                f"{query_key}: минимальная дата {dmin.date()} вместо ожидаемой "
                f"~{first}. Данные неполные — запись в Postgres отменена."
            )
    return df


def get_postgres_engine():
    host = os.environ.get("PGHOST")
    port = os.environ.get("PGPORT", "5432")
    database = os.environ.get("PGDATABASE")
    user = os.environ.get("PGUSER")
    password = os.environ.get("PGPASSWORD")

    missing = [
        name
        for name, val in [
            ("PGHOST", host),
            ("PGDATABASE", database),
            ("PGUSER", user),
            ("PGPASSWORD", password),
        ]
        if not val
    ]
    if missing:
        raise RuntimeError(
            "Не заданы переменные окружения для Postgres: " + ", ".join(missing)
        )

    url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
    return create_engine(url)


def main():
    print("1/5: аутентификация в Power BI...")
    token = get_access_token()

    print("2/5: поиск воркспейса и датасета...")
    group_id = get_workspace_id(token, WORKSPACE_NAME)
    dataset_id = get_dataset_id(token, group_id)
    print(f"    workspace_id={group_id} dataset_id={dataset_id}")

    # Сначала выкачиваем ВСЁ и проверяем, и только потом трогаем Postgres.
    # Раньше вьюхи дропались до выгрузки, и упавший на середине прогон
    # оставлял базу без вьюх и с частично затёртыми таблицами.
    print("3/5: выполнение DAX-запросов...")
    frames = {}
    for query_key, dax in QUERIES.items():
        print(f"    -> {query_key}: выполняю DAX...")
        df = run_dax_windowed(token, group_id, dataset_id, dax, query_key)
        print(f"       ИТОГО строк: {len(df)}, колонок: {len(df.columns)}")
        frames[query_key] = df

    schema = os.environ.get("PGSCHEMA", "public")
    engine = get_postgres_engine()

    print("4/5: удаляю зависимые вьюхи (пересоздаются через join_marketplaces.sql)...")
    with engine.begin() as conn:
        for view_name in DEPENDENT_VIEWS:
            conn.execute(text(f'DROP VIEW IF EXISTS {schema}."{view_name}" CASCADE'))

    print("5/5: загрузка в Postgres...")
    for query_key, df in frames.items():
        table_name = TARGET_TABLES[query_key]
        df.to_sql(table_name, engine, schema=schema, if_exists="replace", index=False)
        print(f"    записано в {schema}.{table_name} ({len(df)} строк)")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка: {exc}", file=sys.stderr)
        sys.exit(1)