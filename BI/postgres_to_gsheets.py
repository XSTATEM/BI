"""
Пайплайн: Postgres (v_marketplaces_full, v_warehouse_stocks_fbs,
v_stocks_all_total, v_stocks_by_marketplace) -> Google Sheets.

Аутентификация — Google Service Account (JSON-ключ). Сам ключ нигде не
хранится в коде и не передаётся через чат, только путь к файлу через
переменную окружения. Разовая настройка:

  1. В Google Cloud Console (console.cloud.google.com) создать/выбрать
     проект и включить "Google Sheets API" (и "Google Drive API", если
     таблицы создаются впервые скриптом, а не вручную).
  2. Там же: IAM & Admin -> Service Accounts -> Create Service Account.
     После создания -> Keys -> Add key -> JSON. Скачается файл вида
     my-project-1234-abcd1234.json — положите его на сервер отдельно
     от репозитория (например, /home/user/BI/secrets/gsheets-sa.json)
     и НЕ коммитьте его никуда.
  3. Откройте нужную Google-таблицу в браузере -> кнопка "Настройки
     доступа" -> добавьте email сервисного аккаунта (строка "client_email"
     внутри JSON-ключа, вида ...@...iam.gserviceaccount.com) с правом
     Редактор.
  4. Скопируйте ID таблицы из её URL:
     https://docs.google.com/spreadsheets/d/<ЭТОТ_ID>/edit

Переменные окружения:
  GOOGLE_SERVICE_ACCOUNT_FILE — путь к JSON-ключу сервисного аккаунта
  GSHEET_ID                   — id целевой Google-таблицы
  GSHEET_TAB                  — имя листа для витрины по маркетплейсам
                                 (по умолчанию "v_marketplaces_full")
  GSHEET_STOCK_TAB            — имя листа для остатков по складам FBS
                                 (по умолчанию "Остатки FBS")
  GSHEET_STOCKS_ALL_TAB       — имя листа для сводных остатков по всем
                                 источникам (по умолчанию "Все остатки")
  GSHEET_STOCKS_MP_TAB        — имя листа для остатков по маркетплейсам
                                 (по умолчанию "Остатки МП")
  GSHEET_OZON_OTHER_TAB       — имя листа для прочих удержаний Ozon
                                 (по умолчанию "Прочие удержания Ozon";
                                 колонка "Прочие удержания, руб" выводится
                                 в формате #,##0.00 — см. NUMBER_FORMATS)
  GSHEET_NOMENCLATURE_TAB     — имя листа для справочника товаров Ozon
                                 (по умолчанию "Справочник Ozon")
  PGHOST / PGPORT / PGDATABASE / PGUSER / PGPASSWORD / PGSCHEMA —
                                 те же, что и в pbi_to_postgres.py

Что делает: читает данные из четырёх вьюх Postgres и записывает их на
четыре листа Google-таблицы, полностью очищая и перезаписывая каждый лист
(аналог if_exists="replace"):
  1. v_marketplaces_full      -> лист GSHEET_TAB (меры по маркетплейсам,
     включая Товаров в пути на МП / от поставщика / Дебиторка авансов
     поставщикам — эти 4 колонки не грейнятся по Дате/МП, см. комментарий
     в join_marketplaces.sql перед CREATE VIEW v_marketplaces_full).
  2. v_warehouse_stocks_fbs   -> лист GSHEET_STOCK_TAB (остатки FBS по
     складам, см. history.SQL, раздел 5): Дата | SKU | Склад | Доступно |
     Зарезервировано | Отгружается | Всего | Заказано | В пути (из
     Power BI, таблица Transfer_items — проставлено только на самую
     свежую дату по каждой паре SKU+Склад, см. history.SQL раздел 5).
  3. v_stocks_all_total       -> лист GSHEET_STOCKS_ALL_TAB (сводный остаток
     FBS+FBW+Ozon+Yandex на SKU+Дата, см. history.SQL, раздел 6): Дата |
     SKU | Всего.
  4. v_stocks_by_marketplace  -> лист GSHEET_STOCKS_MP_TAB (остатки по
     WB/Ozon/Yandex без агрегации, без FBS, см. history.SQL, раздел 6):
     Дата | SKU | Маркетплейс | Остаток, шт.
  5. ozon_nomenclature        -> лист GSHEET_NOMENCLATURE_TAB (справочник
     товаров Ozon, пишет main_ozon.py в G:\script, не Power BI): Артикул |
     Название | Штрихкод | SKU FBO | SKU FBS | Тип товара | Категория |
     Вес | Ед. веса | Ширина | Высота | Длина | Ед. габаритов |
     Объёмный вес | Цена | Цена до скидки | Premium цена | В архиве |
     Client ID (кабинет Ozon, без расшифровки названия - см. accounts.xlsx
     в основном проекте, если нужно название кабинета).
     Себестоимость Ozon не отдаёт - в справочнике её нет.

Запуск:
    GOOGLE_SERVICE_ACCOUNT_FILE=/home/user/BI/secrets/gsheets-sa.json \
    GSHEET_ID=1AbCdEfGhIjKlMnOpQrStUvWxYz \
    PGHOST=... PGPORT=... PGDATABASE=... PGUSER=... PGPASSWORD=... \
        python postgres_to_gsheets.py
"""

import os
import sys

import gspread
import numpy as np
import pandas as pd
from google.oauth2.service_account import Credentials

from pbi_to_postgres import get_postgres_engine

# Числовые форматы ячеек Google Sheets: {имя листа по умолчанию: {колонка: паттерн}}.
# Нужно, потому что value_input_option="RAW" кладёт в ячейку голое число, и
# Google Sheets показывает 45000 вместо 45000,00 — сами по себе нули после
# запятой не появятся, их даёт именно формат ячейки. Паттерн в синтаксисе
# Google Sheets (тот же, что в "Формат -> Числа -> Другие форматы").
NUMBER_FORMATS = {
    "Прочие удержания Ozon": {"Прочие удержания, руб": "#,##0.00"},
}

# (SOURCE_QUERY, переменная окружения с именем листа, имя листа по умолчанию)
EXPORTS = [
    ("SELECT * FROM v_marketplaces_full", "GSHEET_TAB", "v_marketplaces_full"),
    (
        'SELECT * FROM v_warehouse_stocks_fbs ORDER BY "Дата", "SKU", "Склад"',
        "GSHEET_STOCK_TAB",
        "Остатки FBS",
    ),
    (
        'SELECT * FROM v_stocks_all_total ORDER BY "Дата", "SKU"',
        "GSHEET_STOCKS_ALL_TAB",
        "Все остатки",
    ),
    (
        'SELECT * FROM v_stocks_by_marketplace ORDER BY "Дата", "SKU", "Маркетплейс"',
        "GSHEET_STOCKS_MP_TAB",
        "Остатки МП",
    ),
    # Прочие удержания Ozon: дата + кабинет + тип начисления, без SKU.
    # Источник — таблица fact_ozon_other_deductions (не вьюха): её пишет
    # напрямую pbi_to_postgres.py из DAX-запроса "raw_ozon_other".
    (
        'SELECT * FROM fact_ozon_other_deductions'
        ' ORDER BY "Дата", "Магазин", "Прочие удержания, руб" DESC',
        "GSHEET_OZON_OTHER_TAB",
        "Прочие удержания Ozon",
    ),
    # Справочник товаров Ozon: пишет main_ozon.py (get_nomenclature_un) в
    # G:\script, не Power BI. client_id - id кабинета Ozon как есть, без
    # расшифровки в название (сопоставление - в accounts.xlsx основного
    # проекта). Себестоимости здесь нет - Ozon её не отдаёт через API.
    (
        '''
        SELECT
            offer_id AS "Артикул",
            name AS "Название",
            barcode AS "Штрихкод",
            sku_fbo AS "SKU FBO",
            sku_fbs AS "SKU FBS",
            type_name AS "Тип товара",
            description_category_name AS "Категория",
            weight AS "Вес",
            weight_unit AS "Ед. веса",
            width AS "Ширина",
            height AS "Высота",
            depth AS "Длина",
            dimension_unit AS "Ед. габаритов",
            volume_weight AS "Объёмный вес",
            price AS "Цена",
            old_price AS "Цена до скидки",
            premium_price AS "Premium цена",
            is_archived AS "В архиве",
            client_id AS "Client ID"
        FROM ozon_nomenclature
        ORDER BY offer_id, client_id
        ''',
        "GSHEET_NOMENCLATURE_TAB",
        "Справочник Ozon",
    ),
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]


def to_cell_value(v):
    """Готовит одно значение ячейки для gspread.

    Раньше весь датафрейм приводился к строкам (df.astype(str)) — из-за
    этого числа попадали в Google Sheets как текст, и SUM()/AVERAGE() по
    таким колонкам считали 0. Здесь числа остаются числами (int/float),
    даты приводятся к обычной строке даты, а всё остальное — в текст.

    ВАЖНО: некоторые колонки (например, "ДРР, %", "Ср. цена, руб") в самой
    Postgres хранятся как text (см. комментарий в начале join_marketplaces.sql
    про разнотипность после pandas.to_sql) — они и здесь останутся текстом,
    формулы по ним всё равно не сработают, пока не поменяете тип колонки
    в БД на double precision.
    """
    if pd.isna(v):
        return ""
    if isinstance(v, (pd.Timestamp,)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, (np.integer, np.floating)):
        return v.item()
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v
    return str(v)


def get_gsheet_client() -> gspread.Client:
    key_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    if not key_file:
        raise RuntimeError("Не задана переменная окружения GOOGLE_SERVICE_ACCOUNT_FILE")
    if not os.path.exists(key_file):
        raise RuntimeError(f"Файл ключа сервисного аккаунта не найден: {key_file}")
    creds = Credentials.from_service_account_file(key_file, scopes=SCOPES)
    return gspread.authorize(creds)


def write_dataframe_to_sheet(sh: gspread.Spreadsheet, tab_name: str, df: pd.DataFrame,
                             formats: dict | None = None) -> None:
    """Полностью очищает (или создаёт) лист tab_name и записывает df заново.

    formats — {имя колонки: числовой паттерн Google Sheets}, применяется к
    диапазону колонки со 2-й строки. Значения в ячейках остаются числами,
    меняется только их отображение.
    """
    try:
        ws = sh.worksheet(tab_name)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab_name, rows=1, cols=1)

    values = [df.columns.tolist()]
    values.extend(
        [to_cell_value(v) for v in row] for row in df.itertuples(index=False)
    )
    ws.resize(rows=max(len(values), 1), cols=max(len(df.columns), 1))
    ws.update(values, value_input_option="RAW")

    for col_name, pattern in (formats or {}).items():
        if col_name not in df.columns:
            print(f"    ВНИМАНИЕ: колонки '{col_name}' нет на листе '{tab_name}', формат не применён")
            continue
        # A1-нотация: колонка по её порядковому номеру, со 2-й строки (без шапки)
        letter = gspread.utils.rowcol_to_a1(1, df.columns.get_loc(col_name) + 1).rstrip("1")
        cell_range = f"{letter}2:{letter}{len(values)}"
        ws.format(cell_range, {"numberFormat": {"type": "NUMBER", "pattern": pattern}})
        print(f"    формат '{pattern}' применён к '{col_name}' ({cell_range})")


def main():
    sheet_id = os.environ.get("GSHEET_ID")
    if not sheet_id:
        raise RuntimeError("Не задана переменная окружения GSHEET_ID")

    print("1/3: подключаюсь к Postgres и Google Sheets...")
    engine = get_postgres_engine()
    gc = get_gsheet_client()
    sh = gc.open_by_key(sheet_id)

    total = len(EXPORTS)
    for i, (query, tab_env_var, default_tab) in enumerate(EXPORTS, start=1):
        tab_name = os.environ.get(tab_env_var, default_tab)
        print(f"2/3 [{i}/{total}]: читаю '{tab_name}' из Postgres...")
        df = pd.read_sql(query, engine)
        print(f"    строк: {len(df)}, колонок: {len(df.columns)}")

        print(f"3/3 [{i}/{total}]: записываю данные в лист '{tab_name}'...")
        write_dataframe_to_sheet(sh, tab_name, df, NUMBER_FORMATS.get(default_tab))

    print("Готово.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка: {exc}", file=sys.stderr)
        sys.exit(1)
