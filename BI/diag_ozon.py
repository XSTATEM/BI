"""
Диагностика расхождения raw_ozon: XMLA отдаёт 19796 строк с 21.05,
executeQueries (REST) — 12298 строк с 03.08.

Запускать на сервере из той же папки, что и pbi_to_postgres.py:
    cd /home/user/BI && python3 diag_ozon.py

Ничего не пишет в Postgres — только читает и печатает.
"""

import json
import sys

import pandas as pd
import requests

from powerbi_auth import get_access_token
from dax_queries import QUERIES

PBI_API = "https://api.powerbi.com/v1.0/myorg"
WORKSPACE_NAME = "echips.ru"

PERIOD_AND_SKU = """
VAR _period = DATESINPERIOD('Календарь'[Date], TODAY(), -90, DAY)
VAR _sku =
    FILTER(
        ALL('Справочник SKU'),
        'Справочник SKU'[На Ozon] = "Да"
            || CALCULATE('_МЕРЫ OZON'[Продажи, руб Oz], _period) <> 0
            || CALCULATE('_МЕРЫ OZON'[Возвраты, руб Oz], _period) <> 0
            || CALCULATE('_МЕРЫ OZON'[Прочее, руб Oz], _period) <> 0
            || CALCULATE('_МЕРЫ OZON'[Продвижение по SKU %, руб Oz], _period) <> 0
    )
"""

GROUPBY = """
        'Справочник SKU'[SKU (ключ)],
        'Календарь'[Date],
        'Справочник SKU'[Направление],
"""


def variant(name, measures):
    return name, f"""EVALUATE{PERIOD_AND_SKU}RETURN
CALCULATETABLE(
    SUMMARIZECOLUMNS(
{GROUPBY}{measures}
    ),
    _period,
    _sku
)
"""


VARIANTS = [
    variant("1. только выручка",
            '        "FR_Выручка по выкупам, руб", [Выручка по выкупам, руб Oz]'),
    variant("2. только цена в ЛК",
            '        "Цена в ЛК", \'_МЕРЫ OZON\'[Цена в ЛК, руб Oz]'),
    variant("3. выручка + цена",
            '        "Цена в ЛК", \'_МЕРЫ OZON\'[Цена в ЛК, руб Oz],\n'
            '        "FR_Выручка по выкупам, руб", [Выручка по выкупам, руб Oz]'),
    variant("4. выручка + остаток (на сегодня)",
            '        "Ост", \'_МЕРЫ WAREHOUSE\'[Остаток Ozon (на сегодня)],\n'
            '        "FR_Выручка по выкупам, руб", [Выручка по выкупам, руб Oz]'),
    ("5. ПОЛНЫЙ raw_ozon из dax_queries.py", QUERIES["raw_ozon"]),
]


def get_ids(token):
    r = requests.get(f"{PBI_API}/groups", headers={"Authorization": f"Bearer {token}"},
                     params={"$filter": f"name eq '{WORKSPACE_NAME}'"}, timeout=30)
    r.raise_for_status()
    gid = r.json()["value"][0]["id"]

    r = requests.get(f"{PBI_API}/groups/{gid}/datasets",
                     headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    datasets = r.json()["value"]
    print(f"Датасетов в воркспейсе: {len(datasets)}")
    for d in datasets:
        print(f"    {d['id']}  name={d.get('name')!r}")
    return gid, datasets


def run(token, gid, did, dax):
    url = f"{PBI_API}/groups/{gid}/datasets/{did}/executeQueries"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"queries": [{"query": dax}],
              "serializerSettings": {"includeNulls": True}},
        timeout=300,
    )
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}: {resp.text[:400]}"

    payload = resp.json()
    result = payload["results"][0]
    # ключи помимо tables — сюда Power BI кладёт предупреждения об усечении
    extra = {k: v for k, v in result.items() if k != "tables"}
    rows = result["tables"][0]["rows"]
    df = pd.DataFrame(rows)
    df.columns = [c.split("[")[-1].rstrip("]") if "[" in c else c for c in df.columns]
    return df, extra


def main():
    token = get_access_token()
    gid, datasets = get_ids(token)
    did = datasets[0]["id"] if len(datasets) == 1 else next(
        d["id"] for d in datasets if d.get("name") == "Echips_FR")
    print(f"Используется dataset_id={did}\n")
    print("=" * 78)

    for name, dax in VARIANTS:
        df, extra = run(token, gid, did, dax)
        if df is None:
            print(f"{name}\n    ОШИБКА: {extra}\n")
            continue

        datecol = next((c for c in df.columns if c.lower() == "date"), None)
        dmin = dmax = "-"
        if datecol:
            d = pd.to_datetime(df[datecol], errors="coerce", format="mixed")
            dmin, dmax = d.min(), d.max()

        revcol = next((c for c in df.columns if "Выручка по выкупам, руб" in c), None)
        rev = pd.to_numeric(df[revcol], errors="coerce").sum() if revcol else 0

        print(f"{name}")
        print(f"    строк: {len(df):>7}   колонок: {len(df.columns)}")
        print(f"    даты:  {dmin} .. {dmax}")
        print(f"    выручка: {rev:,.0f}")
        if extra:
            print(f"    !! доп. поля ответа: {json.dumps(extra, ensure_ascii=False)[:300]}")
        print("-" * 78)

    print("\nОжидаемое из модели (проверено по XMLA):")
    print("    1. только выручка        -> ~2 242 строки, с 21.05")
    print("    2. только цена           -> ~13 364 строки, с 03.08")
    print("    3. выручка + цена        -> ~15 384 строки, с 21.05")
    print("    5. полный raw_ozon       -> ~19 796 строк, с 21.05, 117 992 349 руб")
    print("\nГде цифра впервые разойдётся с ожидаемой — там и причина.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка: {exc}", file=sys.stderr)
        sys.exit(1)
