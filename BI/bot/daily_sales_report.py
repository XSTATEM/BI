"""
Пайплайн: Postgres (v_marketplaces_full, v_warehouse_stocks_full)
    -> поиск аномалий (правила/пороги)
    -> текст отчёта (Claude API, с резервным шаблоном без LLM)
    -> Telegram (Bot API, sendMessage).

Логика полностью отделена от Power BI: скрипт читает те же вьюхи, что и
postgres_to_gsheets.py, поэтому его можно запускать сразу после
pbi_to_postgres.py + join_marketplaces.sql в общем пайплайне, либо отдельно
по расписанию (данные в Postgres обновляются pbi_to_postgres.py, а не этим
скриптом).

Что ищем (все пороги настраиваются через переменные окружения, см. ниже):
  1. revenue    — дневная выручка по (Маркетплейс, Направление) отклонилась
                  от типичного значения для этого дня недели (среднее по
                  прошлым неделям) больше чем на ANOMALY_PCT_THRESHOLD% или
                  ANOMALY_Z_THRESHOLD стандартных отклонений.
  2. sku_movers — топ SKU по изменению выручки день-к-дню (без порога,
                  просто самые заметные движения — растущие и падающие).
  3. drr        — среднедневной ДРР (% рекламных расходов от выручки) по
                  (Маркетплейс, Направление) скакнул больше чем на
                  DRR_PP_THRESHOLD процентных пунктов от своего среднего.
  4. stock      — остатки на складе (v_warehouse_stocks_full, "Доступно")
                  на последнюю дату ниже STOCK_LOW_QTY.
  5. low_days   — "Запас, дни" (только WB) ниже STOCK_LOW_DAYS.
  6. plan       — факт выручки с начала недели vs план, прорейтированный по
                  прошедшим дням недели ("День Сортировка"), отклонение
                  больше PLAN_PACE_THRESHOLD_PCT%.

Текст отчёта:
  Если задан ANTHROPIC_API_KEY — найденные аномалии (уже посчитанные,
  а не сырые данные) отправляются в Claude с просьбой собрать их в связный
  русский текст для Telegram. Если ключа нет или вызов упал — используется
  простой шаблон (render_fallback_text) без LLM, тоже на русском.
  Модель Claude ничего не "придумывает" — только форматирует уже посчитанные
  находки, все числа берутся из findings.

Переменные окружения:
  Postgres:      PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD, PGSCHEMA
                 (те же, что и в pbi_to_postgres.py)
  Telegram:      TELEGRAM_BOT_TOKEN — токен бота от @BotFather
                 TELEGRAM_CHAT_ID   — id чата/канала, куда слать отчёт
                                      (узнать: написать боту, затем открыть
                                      https://api.telegram.org/bot<TOKEN>/getUpdates
                                      и найти "chat":{"id": ...})
  Графики (опц.): пакет matplotlib — если установлен, к дневному отчёту
                                      (📊 Продажи, build_daily_report()) сверх
                                      текста прикладывается PNG с трендом
                                      выручки/рекламы по дням (см.
                                      build_kpi_chart_png()). Без matplotlib —
                                      просто пропускается, отчёт не ломается.
                                      pip install matplotlib
  LLM (опц.):    ANTHROPIC_API_KEY  — если не задан, отчёт соберётся по
                                      шаблону без LLM
                 ANTHROPIC_MODEL    — по умолчанию "claude-sonnet-5"
                 ANTHROPIC_BASE_URL — опц., переопределить эндпоинт вместо
                                      api.anthropic.com (например, для
                                      прокси-провайдеров биллинга в РФ).
                                      Данные (агрегированные находки, не сырые
                                      продажи) в этом случае идут через
                                      сторонний сервис — учитывайте при выборе
  Пороги (опц., есть значения по умолчанию):
                 ANOMALY_LOOKBACK_DAYS   (35)  — сколько дней истории тянуть
                 ANOMALY_PCT_THRESHOLD   (20)  — % отклонения выручки/дня
                 ANOMALY_Z_THRESHOLD     (2.0) — z-score выручки/дня
                 MIN_REVENUE_FOR_CHECK   (500) — не проверять совсем мелкие
                                                  направления (шум)
                 DRR_PP_THRESHOLD        (10)  — скачок ДРР, п.п.
                 STOCK_LOW_QTY           (5)   — критичный остаток, шт
                 STOCK_LOW_DAYS          (5)   — критичный запас, дней
                 PLAN_PACE_THRESHOLD_PCT (15)  — отставание/опережение плана, %

Доп. разделы для интерактивного бота (telegram_bot.py, кнопки меню) —
каждый строит отдельный текст независимо от build_report_text() выше:
  build_ads_report_text()         — 📢 Реклама: расход на продвижение и ДРР
                                     за период vs предыдущий период, ROAS.
                                     Env: AD_REPORT_PERIOD_DAYS (14)
  build_finance_report_text()     — 💰 Финансы: маржа (руб/%), MP cost %,
                                     дебиторка за период vs предыдущий период.
                                     Env: FIN_REPORT_PERIOD_DAYS (14)
  build_expenses_report_text()    — 💸 Расходы: разбивка по статьям
                                     (себестоимость, комиссия, эквайринг,
                                     логистика, продвижение, удержания),
                                     % от выручки, vs предыдущий период.
                                     Env: EXPENSE_REPORT_PERIOD_DAYS (14)
  build_correlation_report_text() — 🔗 Зависимости: корреляция Пирсона между
                                     дневными метриками (выручка, реклама,
                                     ДРР, маржа %, MP cost %, конверсия,
                                     негативы, рейтинг, запас дней) —
                                     топ самых сильных связей, |r| ≥ порога.
                                     Корреляция ≠ причинность, отдельно
                                     оговаривается в тексте отчёта.
                                     Env: CORR_LOOKBACK_DAYS (60),
                                          CORR_MIN_ABS (0.4)
  build_patterns_report_text()    — 🧩 Паттерны: сезонность выручки по дням
                                     недели (устойчивое отклонение от среднего
                                     по направлению) + устойчивые недельные
                                     тренды роста/падения (ранговая корреляция
                                     номера недели и выручки).
                                     Env: PATTERN_LOOKBACK_DAYS (70),
                                          PATTERN_WEEKDAY_PCT (15),
                                          PATTERN_TREND_RHO (0.6),
                                          PATTERN_MIN_WEEKDAY_SAMPLES (4),
                                          PATTERN_MIN_WEEKS (5)
  build_reconciliation_report_text()
                                  — 🔍 Сверка: ручная сверка по одному
                                     маркетплейсу + номеру недели (+ опционально
                                     направление) — сумма выручки по выкупам,
                                     маржи и расходов на рекламу за эту неделю.
                                     Номер недели вводится текстом в боте (ISO-
                                     неделя, см. week_number_to_range()); список
                                     направлений для клавиатуры — через
                                     list_directions_for_week().

Все пять (ads/finance/expenses/correlation/patterns) — детерминированные (без
LLM): цифры уже посчитаны в Python, шаблон только форматирует. build_expenses_
report_text и build_correlation_report_text дополнительно разбивают находки по
"Направление" (не только по "Маркетплейс", как раньше). Кнопки меню и роутинг
между разделами — в telegram_bot.py.

Все пять принимают опциональный второй аргумент period (Period, см. класс
ниже) — пресет "N дней" или явный диапазон дат. Без period (например, при
вызове из cron/main()) каждая функция берёт days_back из своей ENV-переменной
выше — поведение не меняется. Выбор периода пользователем (кнопка -> "7/14/30
дней"/"Свой период" -> для кастомного периода — ввод дат текстом) реализован
в telegram_bot.py, здесь только Period + period_window()/fetch_days_for_period()
+ parse_custom_period_text() как общие утилиты.

Во всех отчётах (включая детекторы аномалий в build_daily_report()) "сегодня"
никогда не анализируется — load_marketplace_data() всегда режет данные по
"вчера" включительно (см. комментарий в самой функции), т.к. данные из
маркетплейсов доезжают до Postgres с задержкой примерно в сутки.

Запуск:
    TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... \\
    ANTHROPIC_API_KEY=... \\
    PGHOST=... PGPORT=... PGDATABASE=... PGUSER=... PGPASSWORD=... \\
        python daily_sales_report.py

Расписание: см. README ("Ежедневный отчёт для продажников") — можно через
cron рядом с остальным пайплайном, либо через планировщик задач Cowork.
"""

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO

import pandas as pd
import requests

from pbi_to_postgres import get_postgres_engine

# Графики (опц.) — если matplotlib не установлен, build_kpi_chart_png() просто
# возвращает None и отчёт уходит без картинки, ничего не падает.
try:
    import matplotlib
    matplotlib.use("Agg")  # без дисплея (сервер/сандбокс) — рендер сразу в файл
    import matplotlib.pyplot as plt
    _HAS_MATPLOTLIB = True
except ImportError:
    _HAS_MATPLOTLIB = False

# В боевой v_marketplaces_full эта колонка называется с префиксом "FR_"
# (см. \d v_marketplaces_full) — без префикса такой колонки нет.
REVENUE_COL = "FR_Выручка по выкупам без НДС, руб"
TELEGRAM_MAX_LEN = 4096

# Рублёвая мера расходов на продвижение, консистентная по всем 3 МП (см.
# dax_queries.py: везде источник назван "Продвижение, руб <MP>"). Колонку
# "FR_Продвижение, руб" (с запятой) для этого НЕ использовать — там для
# Yandex источник в DAX буквально называется "Продвижение, % YAM", т.е.
# скорее всего это %, а не рубли, несмотря на суффикс "руб" в имени колонки.
AD_SPEND_COL = "FR_Продвижение"

# Статьи расходов для разбивки (💸 Расходы). "FR_Себес УУс" сознательно не
# включена — это дубликат "FR_Себестоимость, руб" (см. join_marketplaces.sql).
COST_COLUMNS = [
    ("FR_Себестоимость, руб", "Себестоимость"),
    ("FR_Комиссия", "Комиссия МП"),
    ("FR_Эквайринг", "Эквайринг"),
    ("FR_Логистика прямая", "Логистика прямая"),
    ("FR_Обратная и прочая логистика", "Обратная/прочая логистика"),
    ("FR_Прочие удержания", "Прочие удержания"),
    (AD_SPEND_COL, "Продвижение (реклама)"),
]


# ---------------------------------------------------------------------------
# Загрузка данных
# ---------------------------------------------------------------------------

def load_marketplace_data(engine, days_back: int) -> pd.DataFrame:
    # "Date" в v_marketplaces_full хранится как text (см. join_marketplaces.sql),
    # поэтому сравнение с CURRENT_DATE требует явного cast — без него Postgres
    # падает с "operator does not exist: text >= timestamp without time zone".
    #
    # "< CURRENT_DATE" (а не "<= CURRENT_DATE") — сегодняшний день сознательно
    # никогда не участвует в анализе: данные из маркетплейсов доезжают до
    # Power BI/Postgres с задержкой примерно в сутки, поэтому строки за
    # "сегодня" почти всегда либо отсутствуют, либо заведомо неполные и дают
    # ложные "выручка упала на 100%". Все функции (детекторы аномалий, 5
    # кнопок отчётов, Сверка) читают данные через эту функцию, так что курсор
    # "не позже вчера" действует для них всех одинаково.
    query = f"""
        SELECT *
        FROM v_marketplaces_full
        WHERE "Date"::date >= CURRENT_DATE - INTERVAL '{int(days_back)} days'
          AND "Date"::date < CURRENT_DATE
    """
    df = pd.read_sql(query, engine)
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def load_stock_data(engine) -> pd.DataFrame:
    query = 'SELECT * FROM v_warehouse_stocks_full ORDER BY "Дата" DESC'
    df = pd.read_sql(query, engine)
    df["Дата"] = pd.to_datetime(df["Дата"])
    return df


def parse_percent(series: pd.Series) -> pd.Series:
    """"ДРР, %" хранится в Postgres как text и по-разному отформатирован
    у разных маркетплейсов (см. комментарий в начале join_marketplaces.sql).
    Приводим к float, всё, что не парсится, -> NaN."""
    cleaned = (
        series.astype(str)
        .str.strip()
        .str.replace("%", "", regex=False)
        .str.replace(",", ".", regex=False)
        .replace({"": None, "None": None, "nan": None})
    )
    values = pd.to_numeric(cleaned, errors="coerce")
    # При делении на нулевую выручку DAX отдаёт Infinity, которая доезжает
    # сюда как текст "inf"/"-inf" и парсится to_numeric как настоящая
    # бесконечность (не NaN) — без этой строки такие строки давали в отчёте
    # "ДРР упала до inf%" вместо того, чтобы просто быть пропущенными как
    # недостаточные данные.
    return values.replace([float("inf"), float("-inf")], pd.NA)


# ---------------------------------------------------------------------------
# Детекторы аномалий — каждый возвращает список dict с готовым полем "текст"
# (человекочитаемая строка на русском) + сырыми числами для LLM-контекста.
# ---------------------------------------------------------------------------

def detect_revenue_anomalies(df, pct_threshold, z_threshold, min_revenue):
    daily = (
        df.groupby(["Date", "Маркетплейс", "Направление"])[REVENUE_COL]
        .sum()
        .reset_index()
    )
    if daily.empty:
        return []
    last_date = daily["Date"].max()
    findings = []
    for (mp, dirn), grp in daily.groupby(["Маркетплейс", "Направление"]):
        grp = grp.sort_values("Date")
        today_row = grp[grp["Date"] == last_date]
        if today_row.empty:
            continue
        today_value = float(today_row[REVENUE_COL].iloc[0])

        history = grp[grp["Date"] < last_date]
        if len(history) < 5:
            continue
        if today_value < min_revenue and history[REVENUE_COL].mean() < min_revenue:
            continue  # слишком маленькое направление, чтобы % отклонения были осмысленны

        same_weekday = history[history["Date"].dt.dayofweek == last_date.dayofweek][REVENUE_COL]
        baseline = same_weekday if len(same_weekday) >= 2 else history[REVENUE_COL]
        mean = baseline.mean()
        std = baseline.std(ddof=0) or 0.0
        if mean <= 0:
            continue

        pct_dev = (today_value - mean) / mean * 100
        z = (today_value - mean) / std if std > 0 else 0.0
        if abs(pct_dev) < pct_threshold and abs(z) < z_threshold:
            continue

        direction = "выше" if pct_dev > 0 else "ниже"
        findings.append({
            "маркетплейс": mp,
            "направление": dirn,
            "факт_руб": round(today_value),
            "обычно_руб": round(mean),
            "отклонение_%": round(pct_dev, 1),
            "z_score": round(z, 2),
            "текст": (
                f"{mp}/{dirn}: выручка {round(today_value):,} ₽ — на {abs(round(pct_dev, 1))}% "
                f"{direction} обычного для этого дня недели ({round(mean):,} ₽)"
            ).replace(",", " "),
        })
    findings.sort(key=lambda f: abs(f["отклонение_%"]), reverse=True)
    return findings


def detect_sku_top_movers(df, top_n=5):
    last_date = df["Date"].max()
    prev_date = last_date - pd.Timedelta(days=1)
    subset = df[df["Date"].isin([prev_date, last_date])]
    if subset.empty:
        return []

    pivot = (
        subset.groupby(["SKU (ключ)", "Название товара", "Date"])[REVENUE_COL]
        .sum()
        .reset_index()
        .pivot_table(index=["SKU (ключ)", "Название товара"], columns="Date", values=REVENUE_COL, fill_value=0)
    )
    if prev_date not in pivot.columns or last_date not in pivot.columns:
        return []

    pivot = pivot[(pivot[prev_date] > 0) | (pivot[last_date] > 0)]
    if pivot.empty:
        return []

    pivot["delta"] = pivot[last_date] - pivot[prev_date]
    top = pivot.reindex(pivot["delta"].abs().sort_values(ascending=False).index).head(top_n)

    findings = []
    for (sku, name), row in top.iterrows():
        prev_val, today_val, delta = row[prev_date], row[last_date], row["delta"]
        pct = (delta / prev_val * 100) if prev_val > 0 else None
        arrow = "вырос" if delta > 0 else "упал"
        pct_text = f" ({abs(round(pct, 1))}%)" if pct is not None else ""
        findings.append({
            "sku": sku,
            "название": name,
            "вчера_руб": round(prev_val),
            "сегодня_руб": round(today_val),
            "дельта_руб": round(delta),
            "дельта_%": round(pct, 1) if pct is not None else None,
            "текст": f"{name} ({sku}): {arrow} на {abs(round(delta)):,} ₽{pct_text}".replace(",", " "),
        })
    return findings


def detect_drr_anomalies(df, pp_threshold):
    df = df.copy()
    df["ДРР_num"] = parse_percent(df["ДРР, %"])
    daily = (
        df.groupby(["Date", "Маркетплейс", "Направление"])["ДРР_num"]
        .mean()
        .reset_index()
    )
    if daily.empty:
        return []
    last_date = daily["Date"].max()
    findings = []
    for (mp, dirn), grp in daily.groupby(["Маркетплейс", "Направление"]):
        grp = grp.sort_values("Date")
        today_row = grp[grp["Date"] == last_date]
        if today_row.empty or pd.isna(today_row["ДРР_num"].iloc[0]):
            continue
        history = grp[grp["Date"] < last_date]["ДРР_num"].dropna()
        if len(history) < 5:
            continue

        today_value = float(today_row["ДРР_num"].iloc[0])
        mean = history.mean()
        diff_pp = today_value - mean
        if abs(diff_pp) < pp_threshold:
            continue

        direction = "выросла" if diff_pp > 0 else "упала"
        findings.append({
            "маркетплейс": mp,
            "направление": dirn,
            "дрр_сегодня_%": round(today_value, 1),
            "дрр_обычно_%": round(mean, 1),
            "изменение_пп": round(diff_pp, 1),
            "текст": (
                f"{mp}/{dirn}: ДРР {direction} до {round(today_value, 1)}% "
                f"(обычно {round(mean, 1)}%)"
            ),
        })
    findings.sort(key=lambda f: abs(f["изменение_пп"]), reverse=True)
    return findings


def detect_stock_anomalies(stock_df, low_qty_threshold):
    if stock_df.empty:
        return []
    last_date = stock_df["Дата"].max()
    latest = stock_df[stock_df["Дата"] == last_date]
    low = latest[latest["Доступно"] <= low_qty_threshold].sort_values("Доступно")

    findings = []
    for _, row in low.iterrows():
        findings.append({
            "sku": row["SKU"],
            "склад": row["Склад"],
            "доступно": row["Доступно"],
            "заказано": row.get("Заказано"),
            "текст": f"{row['SKU']} на складе «{row['Склад']}»: доступно {row['Доступно']} шт",
        })
    return findings


def detect_low_days_of_stock(df, threshold_days):
    if "Запас, дни" not in df.columns:
        return []
    last_date = df["Date"].max()
    latest = df[(df["Date"] == last_date) & df["Запас, дни"].notna()]
    low = latest[latest["Запас, дни"] <= threshold_days].sort_values("Запас, дни")
    # один SKU может встретиться несколько раз (разные "Направление"/строки
    # выгрузки) — оставляем одну строку с минимальным запасом на SKU.
    low = low.drop_duplicates(subset=["SKU (ключ)"], keep="first")

    findings = []
    for _, row in low.iterrows():
        findings.append({
            "sku": row["SKU (ключ)"],
            "название": row.get("Название товара"),
            "запас_дней": row["Запас, дни"],
            "текст": f"{row.get('Название товара', row['SKU (ключ)'])}: запас {row['Запас, дни']} дней (WB)",
        })
    return findings


def detect_plan_pace(df, threshold_pct):
    if "План Выручка, руб" not in df.columns or "Неделя Сортировка" not in df.columns:
        return []
    last_date = df["Date"].max()
    last_week_rows = df[df["Date"] == last_date]
    if last_week_rows.empty:
        return []
    current_week = last_week_rows["Неделя Сортировка"].iloc[0]
    week_df = df[df["Неделя Сортировка"] == current_week]

    grouped = week_df.groupby(["Маркетплейс", "Направление"]).agg(
        факт=(REVENUE_COL, "sum"),
        план=("План Выручка, руб", "first"),
        дней_в_данных=("День Сортировка", "max"),
    ).reset_index()

    findings = []
    for _, row in grouped.iterrows():
        if pd.isna(row["план"]) or row["план"] <= 0 or pd.isna(row["дней_в_данных"]):
            continue
        days_elapsed = max(float(row["дней_в_данных"]), 1.0)
        expected = float(row["план"]) * (days_elapsed / 7.0)
        if expected <= 0:
            continue
        pct_dev = (row["факт"] - expected) / expected * 100
        if abs(pct_dev) < threshold_pct:
            continue

        direction_text = (
            f"план недели опережает на {abs(round(pct_dev, 1))}%"
            if pct_dev > 0
            else f"отстаёт от плана недели на {abs(round(pct_dev, 1))}%"
        )
        findings.append({
            "маркетплейс": row["Маркетплейс"],
            "направление": row["Направление"],
            "факт_с_начала_недели_руб": round(row["факт"]),
            "ожидалось_по_плану_руб": round(expected),
            "отклонение_%": round(pct_dev, 1),
            "текст": (
                f"{row['Маркетплейс']}/{row['Направление']}: {direction_text} "
                f"(факт {round(row['факт']):,} ₽ vs ожидалось {round(expected):,} ₽)"
            ).replace(",", " "),
        })
    findings.sort(key=lambda f: abs(f["отклонение_%"]), reverse=True)
    return findings


# ---------------------------------------------------------------------------
# Доп. отчёты по кнопкам меню (телеграм-бот) — Реклама / Финансы / Расходы /
# Зависимости / Паттерны. Каждый build_*_report_text(engine) сам грузит нужные
# данные и возвращает готовый Markdown-текст, независимо от build_report_text().
# ---------------------------------------------------------------------------

@dataclass
class Period:
    """Период для отчётов по кнопкам меню (телеграм-бот, см. telegram_bot.py):
    либо days_back (пресет "7/14/30 дней" — окно из последних N дней данных),
    либо явный диапазон start/end (кастомные даты, введённые пользователем).
    При запуске без бота (cron, main()) build_*_report_text вызываются без
    period — тогда каждая функция сама берёт days_back из своей ENV-переменной
    (см. докстринг в начале файла), поведение не меняется."""
    days_back: int | None = None
    start: "pd.Timestamp | None" = None
    end: "pd.Timestamp | None" = None

    @property
    def is_custom(self) -> bool:
        return self.start is not None and self.end is not None


CUSTOM_PERIOD_RE = re.compile(
    r"(\d{1,2})\.(\d{1,2})\.?(\d{2,4})?\s*[-–—]\s*(\d{1,2})\.(\d{1,2})\.?(\d{2,4})?"
)


def parse_custom_period_text(text: str) -> "Period | None":
    """Разбирает введённый пользователем текст с диапазоном дат вида
    "01.07.2026-15.07.2026" или "01.07-15.07" (год не указан -> текущий год)
    в Period с явным start/end. Возвращает None, если текст не распознан
    (вызывающий код — telegram_bot.py — должен попросить ввести дату заново)."""
    if not text:
        return None
    m = CUSTOM_PERIOD_RE.search(text.strip())
    if not m:
        return None
    d1, mo1, y1, d2, mo2, y2 = m.groups()
    current_year = pd.Timestamp.today().year
    try:
        year1 = current_year if not y1 else (int(y1) if len(y1) == 4 else 2000 + int(y1))
        year2 = current_year if not y2 else (int(y2) if len(y2) == 4 else 2000 + int(y2))
        start = pd.Timestamp(year=year1, month=int(mo1), day=int(d1))
        end = pd.Timestamp(year=year2, month=int(mo2), day=int(d2))
    except ValueError:
        return None
    if start > end:
        start, end = end, start
    return Period(start=start, end=end)


def fetch_days_for_period(period: "Period", needs_previous: bool = True) -> int:
    """Сколько дней истории запросить у Postgres (load_marketplace_data),
    чтобы окно period — и предыдущий период той же длины для сравнения, если
    needs_previous — точно поместилось в выгрузку."""
    today = pd.Timestamp.today().normalize()
    if period.is_custom:
        span = (period.end - period.start).days + 1
        earliest = period.start - pd.Timedelta(days=span) if needs_previous else period.start
        return max((today - earliest).days + 3, span + 3)
    days_back = period.days_back
    return days_back * (2 if needs_previous else 1) + 3


def period_window(df: pd.DataFrame, period: "Period | int"):
    """Делит df на «текущий» период и «предыдущий» период той же длины перед
    ним — для сравнения period-over-period. period — Period (кастомный
    диапазон start/end или days_back) либо просто int (days_back, для
    обратной совместимости). Возвращает (current, previous, last_date, label)
    — label уже готов для заголовка отчёта."""
    if isinstance(period, int):
        period = Period(days_back=period)

    if period.is_custom:
        start, end = period.start, period.end
        span = (end - start).days + 1
        prev_end = start - pd.Timedelta(days=1)
        prev_start = prev_end - pd.Timedelta(days=span - 1)
        current = df[(df["Date"] >= start) & (df["Date"] <= end)]
        previous = df[(df["Date"] >= prev_start) & (df["Date"] <= prev_end)]
        label = f"{start.date()} – {end.date()}"
        return current, previous, end, label

    days_back = period.days_back
    last_date = df["Date"].max()
    start = last_date - pd.Timedelta(days=days_back - 1)
    prev_end = start - pd.Timedelta(days=1)
    prev_start = prev_end - pd.Timedelta(days=days_back - 1)
    current = df[(df["Date"] >= start) & (df["Date"] <= last_date)]
    previous = df[(df["Date"] >= prev_start) & (df["Date"] <= prev_end)]
    label = f"{days_back} дн. до {last_date.date()}"
    return current, previous, last_date, label


def pct_change(curr, prev):
    if prev is None or pd.isna(prev) or prev == 0:
        return None
    return (curr - prev) / prev * 100


def fmt_rub(x) -> str:
    return f"{round(x):,}".replace(",", " ")


def build_ads_report_text(engine, period: "Period | int | None" = None) -> str:
    if period is None:
        period = Period(days_back=int(os.environ.get("AD_REPORT_PERIOD_DAYS", 14)))
    elif isinstance(period, int):
        period = Period(days_back=period)
    df = load_marketplace_data(engine, fetch_days_for_period(period))
    if df.empty:
        return "Недостаточно данных для отчёта по рекламе."
    df["ДРР_num"] = parse_percent(df["ДРР, %"])
    current, previous, last_date, label = period_window(df, period)

    def agg(part):
        return part.groupby(["Маркетплейс", "Направление"]).agg(
            revenue=(REVENUE_COL, "sum"),
            ad_spend=(AD_SPEND_COL, "sum"),
            drr=("ДРР_num", "mean"),
        ).reset_index()

    cur = agg(current)
    prev = agg(previous).set_index(["Маркетплейс", "Направление"])

    rows = []
    for _, r in cur.sort_values("ad_spend", ascending=False).iterrows():
        key = (r["Маркетплейс"], r["Направление"])
        prev_row = prev.loc[key] if key in prev.index else None
        ad_spend = float(r["ad_spend"]) if pd.notna(r["ad_spend"]) else 0.0
        ad_spend_prev = float(prev_row["ad_spend"]) if prev_row is not None and pd.notna(prev_row["ad_spend"]) else None
        drr = float(r["drr"]) if pd.notna(r["drr"]) else None
        drr_prev = float(prev_row["drr"]) if prev_row is not None and pd.notna(prev_row["drr"]) else None
        revenue = float(r["revenue"])
        if ad_spend <= 0 and not ad_spend_prev:
            continue

        roas = (revenue / ad_spend) if ad_spend > 0 else None
        spend_delta = pct_change(ad_spend, ad_spend_prev)
        drr_delta_pp = (drr - drr_prev) if (drr is not None and drr_prev is not None) else None

        line = f"{r['Маркетплейс']}/{r['Направление']}: расход {fmt_rub(ad_spend)} ₽"
        if spend_delta is not None:
            line += f" ({'+' if spend_delta >= 0 else ''}{round(spend_delta, 1)}% к прошлому периоду)"
        if drr is not None:
            line += f", ДРР {round(drr, 1)}%"
            if drr_delta_pp is not None:
                line += f" ({'+' if drr_delta_pp >= 0 else ''}{round(drr_delta_pp, 1)} п.п.)"
        if roas is not None:
            line += f", ROAS ×{round(roas, 1)}"
        rows.append(line)

    header = f"*📢 Реклама — {label}* (сравнение с предыдущим периодом той же длины)"
    if not rows:
        return f"{header}\n\nРасходов на продвижение за период нет."
    return header + "\n\n" + "\n".join(f"• {l}" for l in rows[:12])


def build_finance_report_text(engine, period: "Period | int | None" = None) -> str:
    if period is None:
        period = Period(days_back=int(os.environ.get("FIN_REPORT_PERIOD_DAYS", 14)))
    elif isinstance(period, int):
        period = Period(days_back=period)
    df = load_marketplace_data(engine, fetch_days_for_period(period))
    if df.empty:
        return "Недостаточно данных для финансового отчёта."
    # "FR_Маржа, %" и "FR_MP Cost, %" хранятся в Postgres как text (см. \d
    # v_marketplaces_full) — парсим в числа тем же способом, что и "ДРР, %",
    # иначе .mean() падает с "dtype 'str' does not support operation 'mean'".
    df = df.copy()
    df["Маржа_%_num"] = parse_percent(df["FR_Маржа, %"])
    df["MP_Cost_%_num"] = parse_percent(df["FR_MP Cost, %"])
    current, previous, last_date, label = period_window(df, period)

    def agg(part):
        return part.groupby(["Маркетплейс", "Направление"]).agg(
            margin_rub=("FR_Маржа, руб", "sum"),
            margin_pct=("Маржа_%_num", "mean"),
            mp_cost_pct=("MP_Cost_%_num", "mean"),
            receivables=("FR_Дебиторка с НДС, руб", "sum"),
        ).reset_index()

    cur = agg(current)
    prev = agg(previous).set_index(["Маркетплейс", "Направление"])

    rows = []
    for _, r in cur.sort_values("margin_rub", ascending=False).iterrows():
        key = (r["Маркетплейс"], r["Направление"])
        prev_row = prev.loc[key] if key in prev.index else None
        margin_rub = float(r["margin_rub"]) if pd.notna(r["margin_rub"]) else 0.0
        margin_prev = float(prev_row["margin_rub"]) if prev_row is not None and pd.notna(prev_row["margin_rub"]) else None
        margin_pct = float(r["margin_pct"]) if pd.notna(r["margin_pct"]) else None
        margin_pct_prev = float(prev_row["margin_pct"]) if prev_row is not None and pd.notna(prev_row["margin_pct"]) else None
        receivables = float(r["receivables"]) if pd.notna(r["receivables"]) else 0.0

        delta = pct_change(margin_rub, margin_prev)
        line = f"{r['Маркетплейс']}/{r['Направление']}: маржа {fmt_rub(margin_rub)} ₽"
        if delta is not None:
            line += f" ({'+' if delta >= 0 else ''}{round(delta, 1)}%)"
        if margin_pct is not None:
            line += f", {round(margin_pct, 1)}% от выручки"
            if margin_pct_prev is not None:
                pp = margin_pct - margin_pct_prev
                line += f" ({'+' if pp >= 0 else ''}{round(pp, 1)} п.п.)"
        if receivables:
            line += f", дебиторка {fmt_rub(receivables)} ₽"
        rows.append(line)

    header = f"*💰 Финансы — {label}* (сравнение с предыдущим периодом той же длины)"
    if not rows:
        return f"{header}\n\nДанных недостаточно."
    return header + "\n\n" + "\n".join(f"• {l}" for l in rows[:12])


def build_expenses_report_text(engine, period: "Period | int | None" = None) -> str:
    if period is None:
        period = Period(days_back=int(os.environ.get("EXPENSE_REPORT_PERIOD_DAYS", 14)))
    elif isinstance(period, int):
        period = Period(days_back=period)
    df = load_marketplace_data(engine, fetch_days_for_period(period))
    if df.empty:
        return "Недостаточно данных для отчёта по расходам."
    current, previous, last_date, period_label = period_window(df, period)

    revenue_cur = float(current[REVENUE_COL].sum())

    rows = []
    for col, cost_label in COST_COLUMNS:
        if col not in current.columns:
            continue
        cur_sum = float(current[col].sum(skipna=True))
        prev_sum = float(previous[col].sum(skipna=True)) if col in previous.columns else 0.0
        if cur_sum == 0 and prev_sum == 0:
            continue
        share = (cur_sum / revenue_cur * 100) if revenue_cur else None
        delta = pct_change(cur_sum, prev_sum)
        rows.append((cur_sum, cost_label, share, delta))

    header = f"*💸 Расходы — {period_label}* (сравнение с предыдущим периодом той же длины)"
    if not rows:
        return f"{header}\n\nДанных о расходах нет."

    rows.sort(key=lambda x: x[0], reverse=True)
    total_cost = sum(r[0] for r in rows)
    share_of_revenue = (total_cost / revenue_cur * 100) if revenue_cur else 0.0
    summary = f"Всего расходов: {fmt_rub(total_cost)} ₽ ({round(share_of_revenue, 1)}% от выручки {fmt_rub(revenue_cur)} ₽)"

    lines = []
    for cur_sum, label, share, delta in rows:
        line = f"{label}: {fmt_rub(cur_sum)} ₽"
        if share is not None:
            line += f" ({round(share, 1)}% от выручки)"
        if delta is not None:
            line += f", {'+' if delta >= 0 else ''}{round(delta, 1)}% к прошлому периоду"
        lines.append(line)

    # Разбивка по направлениям (Маркетплейс/Направление) — сумма всех статей
    # расходов COST_COLUMNS и её доля от выручки этого направления. Отдельно
    # от разбивки по статьям выше, т.к. статья x направление x МП было бы
    # слишком много строк для одного Telegram-сообщения.
    existing_cost_cols = [col for col, _ in COST_COLUMNS if col in current.columns]
    dir_lines = []
    if existing_cost_cols:
        def agg_by_dir(part):
            g = part.groupby(["Маркетплейс", "Направление"])
            cost = g[existing_cost_cols].sum(numeric_only=True).sum(axis=1)
            revenue = g[REVENUE_COL].sum()
            return pd.DataFrame({"cost": cost, "revenue": revenue})

        cur_by_dir = agg_by_dir(current)
        prev_by_dir = agg_by_dir(previous) if not previous.empty else pd.DataFrame(columns=["cost", "revenue"])
        for (mp, dirn), r in cur_by_dir.sort_values("cost", ascending=False).iterrows():
            cost = float(r["cost"])
            revenue_d = float(r["revenue"])
            if cost == 0 and revenue_d == 0:
                continue
            share_d = (cost / revenue_d * 100) if revenue_d else None
            prev_cost = float(prev_by_dir.loc[(mp, dirn), "cost"]) if (mp, dirn) in prev_by_dir.index else None
            delta_d = pct_change(cost, prev_cost)
            line = f"{mp}/{dirn}: {fmt_rub(cost)} ₽"
            if share_d is not None:
                line += f" ({round(share_d, 1)}% от выручки направления)"
            if delta_d is not None:
                line += f", {'+' if delta_d >= 0 else ''}{round(delta_d, 1)}% к прошлому периоду"
            dir_lines.append(line)

    parts = [header, "", summary, "", "\n".join(f"• {l}" for l in lines)]
    if dir_lines:
        parts.append("")
        parts.append("По направлениям:")
        parts.append("\n".join(f"• {l}" for l in dir_lines[:12]))
    return "\n".join(parts)


def build_correlation_report_text(engine, period: "Period | int | None" = None) -> str:
    min_abs_corr = float(os.environ.get("CORR_MIN_ABS", 0.4))
    if period is None:
        period = Period(days_back=int(os.environ.get("CORR_LOOKBACK_DAYS", 60)))
    elif isinstance(period, int):
        period = Period(days_back=period)
    df = load_marketplace_data(engine, fetch_days_for_period(period, needs_previous=False))
    if df.empty:
        return "Недостаточно данных для корреляционного анализа."
    if period.is_custom:
        df = df[(df["Date"] >= period.start) & (df["Date"] <= period.end)]
        label = f"{period.start.date()} – {period.end.date()}"
    else:
        label = f"{period.days_back} дн."
    if df.empty:
        return "Недостаточно данных для корреляционного анализа."
    df["ДРР_num"] = parse_percent(df["ДРР, %"])
    # "FR_Маржа, %" и "FR_MP Cost, %" тоже text в Postgres — парсим так же.
    df["Маржа_pct_num"] = parse_percent(df["FR_Маржа, %"])
    df["MP_cost_pct_num"] = parse_percent(df["FR_MP Cost, %"])

    daily = df.groupby(["Date", "Маркетплейс", "Направление"]).agg(
        Выручка=(REVENUE_COL, "sum"),
        Реклама=(AD_SPEND_COL, "sum"),
        ДРР=("ДРР_num", "mean"),
        Маржа_pct=("Маржа_pct_num", "mean"),
        MP_cost_pct=("MP_cost_pct_num", "mean"),
        CR_общий=("CR Общий, %", "mean"),
        Негативы=("Негативы, %", "mean"),
        Рейтинг=("Рейтинг", "mean"),
        Запас_дни=("Запас, дни", "mean"),
    ).reset_index()

    metric_cols = [
        "Выручка", "Реклама", "ДРР", "Маржа_pct", "MP_cost_pct",
        "CR_общий", "Негативы", "Рейтинг", "Запас_дни",
    ]
    corr = daily[metric_cols].corr(method="pearson", min_periods=15)

    pairs = []
    for i, a in enumerate(metric_cols):
        for b in metric_cols[i + 1:]:
            r = corr.loc[a, b]
            if pd.isna(r) or abs(r) < min_abs_corr:
                continue
            pairs.append((abs(r), r, a, b))
    pairs.sort(key=lambda x: x[0], reverse=True)

    header = f"*🔗 Зависимости — {label}* (корреляция по дням/направлениям)"
    if not pairs:
        return f"{header}\n\nЗаметных линейных зависимостей (|r| ≥ {min_abs_corr}) не найдено."

    labels = {
        "Выручка": "выручка", "Реклама": "расходы на рекламу", "ДРР": "ДРР",
        "Маржа_pct": "маржа, %", "MP_cost_pct": "MP cost, %", "CR_общий": "конверсия в заказ",
        "Негативы": "негативы, %", "Рейтинг": "рейтинг", "Запас_дни": "запас, дней",
    }
    lines = []
    for abs_r, r, a, b in pairs[:8]:
        strength = "сильная" if abs_r >= 0.7 else "умеренная"
        direction = "прямая" if r > 0 else "обратная"
        lines.append(f"{labels[a]} ↔ {labels[b]}: {strength} {direction} связь (r={round(r, 2)})")

    # Разбивка по направлениям — корреляция, посчитанная выше, объединяет все
    # направления в одну выборку и может смазать связи, которые сильны только
    # в одном направлении (или противоположны в разных). Отдельно считаем ту
    # же матрицу на данных одного "Направление" — только если хватает точек
    # (min_periods=15, как и в общем расчёте), иначе строка пропускается.
    by_direction_lines = []
    for dirn, grp in daily.groupby("Направление"):
        dir_corr = grp[metric_cols].corr(method="pearson", min_periods=15)
        dir_pairs = []
        for i, a in enumerate(metric_cols):
            for b in metric_cols[i + 1:]:
                r = dir_corr.loc[a, b]
                if pd.isna(r) or abs(r) < min_abs_corr:
                    continue
                dir_pairs.append((abs(r), r, a, b))
        if not dir_pairs:
            continue
        dir_pairs.sort(key=lambda x: x[0], reverse=True)
        top_r = dir_pairs[0]
        strength = "сильная" if top_r[0] >= 0.7 else "умеренная"
        direction_word = "прямая" if top_r[1] > 0 else "обратная"
        by_direction_lines.append(
            f"{dirn}: {labels[top_r[2]]} ↔ {labels[top_r[3]]} — {strength} {direction_word} связь (r={round(top_r[1], 2)})"
        )

    footer = "_Корреляция не означает причинность — это статистическая связь, не доказательство._"
    parts = [header, "", "\n".join(f"• {l}" for l in lines)]
    if by_direction_lines:
        parts.append("")
        parts.append("Самая сильная связь по направлениям (может отличаться от общей выше):")
        parts.append("\n".join(f"• {l}" for l in by_direction_lines))
    parts.append("")
    parts.append(footer)
    return "\n".join(parts)


def build_patterns_report_text(engine, period: "Period | int | None" = None) -> str:
    weekday_pct_threshold = float(os.environ.get("PATTERN_WEEKDAY_PCT", 15))
    trend_rho_threshold = float(os.environ.get("PATTERN_TREND_RHO", 0.6))
    min_weekday_samples = int(os.environ.get("PATTERN_MIN_WEEKDAY_SAMPLES", 4))
    min_weeks = int(os.environ.get("PATTERN_MIN_WEEKS", 5))
    if period is None:
        period = Period(days_back=int(os.environ.get("PATTERN_LOOKBACK_DAYS", 70)))
    elif isinstance(period, int):
        period = Period(days_back=period)

    df = load_marketplace_data(engine, fetch_days_for_period(period, needs_previous=False))
    if df.empty:
        return "Недостаточно данных для поиска закономерностей."
    if period.is_custom:
        df = df[(df["Date"] >= period.start) & (df["Date"] <= period.end)]
        label = f"{period.start.date()} – {period.end.date()}"
    else:
        label = f"{period.days_back} дн."
    if df.empty:
        return "Недостаточно данных для поиска закономерностей."

    daily = df.groupby(["Date", "Направление"])[REVENUE_COL].sum().reset_index()
    weekday_names = ["понедельникам", "вторникам", "средам", "четвергам", "пятницам", "субботам", "воскресеньям"]

    weekday_lines = []
    for dirn, grp in daily.groupby("Направление"):
        grp = grp.copy()
        grp["weekday"] = grp["Date"].dt.dayofweek
        overall_mean = grp[REVENUE_COL].mean()
        if overall_mean <= 0:
            continue
        by_weekday = grp.groupby("weekday")[REVENUE_COL].agg(["mean", "count"])
        for wd, row in by_weekday.iterrows():
            if row["count"] < min_weekday_samples:
                continue
            dev = (row["mean"] - overall_mean) / overall_mean * 100
            if abs(dev) < weekday_pct_threshold:
                continue
            direction = "выше" if dev > 0 else "ниже"
            weekday_lines.append(
                f"{dirn}: по {weekday_names[int(wd)]} выручка обычно на {abs(round(dev, 1))}% {direction} среднего"
            )

    trend_lines = []
    if "Неделя Сортировка" in df.columns:
        weekly = df.groupby(["Направление", "Неделя Сортировка"])[REVENUE_COL].sum().reset_index()
        for dirn, grp in weekly.groupby("Направление"):
            grp = grp.sort_values("Неделя Сортировка").reset_index(drop=True)
            if len(grp) < min_weeks:
                continue
            week_order = pd.Series(range(len(grp)))
            rho = week_order.corr(grp[REVENUE_COL].rank())
            if pd.isna(rho) or abs(rho) < trend_rho_threshold:
                continue
            span = max(len(grp) // 3, 1)
            first_avg = grp[REVENUE_COL].iloc[:span].mean()
            last_avg = grp[REVENUE_COL].iloc[-span:].mean()
            change = pct_change(last_avg, first_avg)
            direction = "устойчиво растёт" if rho > 0 else "устойчиво снижается"
            change_text = (
                f" ({'+' if change >= 0 else ''}{round(change, 1)}% от начала к концу периода)"
                if change is not None else ""
            )
            trend_lines.append(f"{dirn}: выручка {direction}{change_text}")

    header = f"*🧩 Паттерны — {label}*"
    if not weekday_lines and not trend_lines:
        return f"{header}\n\nУстойчивых закономерностей не обнаружено."

    parts = [header, ""]
    if weekday_lines:
        parts.append("Сезонность по дням недели:")
        parts.extend(f"• {l}" for l in weekday_lines[:8])
        parts.append("")
    if trend_lines:
        parts.append("Устойчивые тренды по неделям:")
        parts.extend(f"• {l}" for l in trend_lines[:8])
    return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# 🔍 Сверка — ручной запрос по одному маркетплейсу + номеру недели (+ опц.
# направление): сумма выручки по выкупам, маржи и расходов на рекламу за эту
# неделю. В отличие от пяти отчётов выше — не сравнивает с предыдущим
# периодом, просто отдаёт сырые суммы за выбранную неделю "как есть", для
# ручной сверки с другими источниками (например, с личным кабинетом МП).
# ---------------------------------------------------------------------------

# Ровно эти три строки использует join_marketplaces.sql в колонке "Маркетплейс"
# (см. 'WB'::text / 'Ozon'::text / 'Yandex'::text) — общий список для
# telegram_bot.py (клавиатура выбора МП) и для валидации здесь.
RECONCILIATION_MARKETPLACES = ["WB", "Ozon", "Yandex"]


def week_number_to_range(week_number: int, year: "int | None" = None) -> "tuple[pd.Timestamp, pd.Timestamp]":
    """Номер ISO-недели -> (понедельник, воскресенье) этой недели. Без year —
    берём текущий год; если результат попадает в будущее (например, сейчас
    неделя 5-я, а пользователь ввёл "40"), это почти наверняка неделя
    прошлого года — пересчитываем на год назад."""
    auto_year = year is None
    if auto_year:
        year = pd.Timestamp.today().year
    try:
        monday = datetime.strptime(f"{year}-W{int(week_number):02d}-1", "%G-W%V-%w")
    except ValueError:
        raise ValueError(f"Некорректный номер недели: {week_number!r}")
    start = pd.Timestamp(monday)
    end = start + pd.Timedelta(days=6)
    if auto_year and start.normalize() > pd.Timestamp.today().normalize():
        return week_number_to_range(week_number, year - 1)
    return start, end


def _load_week_slice(engine, marketplace: str, week_number: int, year: "int | None" = None):
    """Общая часть list_directions_for_week()/build_reconciliation_report_text():
    грузит данные по нужному МП за неделю week_number и возвращает
    (срез_df, start, end)."""
    start, end = week_number_to_range(week_number, year)
    days_back = max((pd.Timestamp.today().normalize() - start).days + 2, 7)
    df = load_marketplace_data(engine, days_back)
    week_df = df[(df["Маркетплейс"] == marketplace) & (df["Date"] >= start) & (df["Date"] <= end)]
    return week_df, start, end


def list_directions_for_week(engine, marketplace: str, week_number: int, year: "int | None" = None) -> list:
    """Список направлений, встречающихся у этого МП на этой неделе — чтобы
    telegram_bot.py мог показать клавиатуру выбора направления, не гадая
    заранее полный список (он разный для разных МП, см. join_marketplaces.sql)."""
    week_df, _start, _end = _load_week_slice(engine, marketplace, week_number, year)
    if week_df.empty or "Направление" not in week_df.columns:
        return []
    return sorted(d for d in week_df["Направление"].dropna().unique().tolist())


def build_reconciliation_report_text(
    engine, marketplace: str, week_number: int, direction: "str | None" = None, year: "int | None" = None
) -> str:
    """🔍 Сверка: сумма "выручка по выкупам" / маржа / расходы на рекламу за
    указанную ISO-неделю, по одному маркетплейсу и (опционально) направлению."""
    week_df, start, end = _load_week_slice(engine, marketplace, week_number, year)
    if direction:
        week_df = week_df[week_df["Направление"] == direction]

    week_title = f"неделя {int(week_number)} ({start.date()}–{end.date()})"
    scope = marketplace + (f"/{direction}" if direction else "")
    header = f"*🔍 Сверка — {scope}, {week_title}*"

    if week_df.empty:
        return f"{header}\n\nДанных за эту неделю нет."

    revenue = float(week_df[REVENUE_COL].sum())
    margin = float(week_df["FR_Маржа, руб"].sum(skipna=True)) if "FR_Маржа, руб" in week_df.columns else None
    ad_spend = float(week_df[AD_SPEND_COL].sum(skipna=True)) if AD_SPEND_COL in week_df.columns else None
    days_present = week_df["Date"].nunique()

    lines = [f"Выручка по выкупам: {fmt_rub(revenue)} ₽"]
    if margin is not None:
        lines.append(f"Маржа: {fmt_rub(margin)} ₽")
    if ad_spend is not None:
        lines.append(f"Расходы на рекламу: {fmt_rub(ad_spend)} ₽")

    parts = [header, "", "\n".join(f"• {l}" for l in lines)]
    if days_present < 7:
        parts.append("")
        parts.append(
            f"_В данных за эту неделю только {days_present} из 7 дней — возможно, "
            "неделя ещё не завершилась или часть данных не догрузилась._"
        )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Текст отчёта
# ---------------------------------------------------------------------------

SECTIONS = [
    ("revenue", "📉 Выручка — отклонения от нормы"),
    ("sku_movers", "🔀 Топ движений по SKU (день к дню)"),
    ("drr", "📢 ДРР — скачки"),
    ("stock", "📦 Критичные остатки (склад)"),
    ("low_days", "⏳ Низкий запас (дней, WB)"),
    ("plan", "🎯 План недели — отставание/опережение"),
]


def render_fallback_text(findings: dict) -> str:
    lines = [f"*Ежедневный отчёт по продажам — {findings['дата']}*", ""]
    if findings.get("данные_отстают"):
        lines.append(
            "_Внимание: последняя дата в данных отстаёт от ожидаемой (обычно "
            "данные догружаются по вчера включительно) — похоже на сбой "
            "пайплайна загрузки, а не на реальную проблему с продажами._"
        )
        lines.append("")
    any_section = False
    for key, title in SECTIONS:
        items = findings.get(key) or []
        if not items:
            continue
        any_section = True
        lines.append(title)
        for item in items[:8]:
            lines.append(f"• {item['текст']}")
        lines.append("")
    if not any_section:
        lines.append("Существенных отклонений не обнаружено.")
    return "\n".join(lines).strip()


def summarize_with_llm(findings: dict, model: str) -> str | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        print("Пакет anthropic не установлен (pip install anthropic), использую шаблон", file=sys.stderr)
        return None

    prompt = (
        "Ты — старший аналитик по продажам на маркетплейсах (Wildberries, "
        "Ozon, Yandex Market) в компании Echips (ноутбуки и сопутствующие "
        "товары). Ниже JSON с уже посчитанными находками/аномалиями за "
        f"{findings['дата']} — все числа уже проверены в Python, НЕ "
        "пересчитывай их, НЕ округляй по-своему и НЕ добавляй находок, "
        "которых нет в JSON.\n\n"
        "Прежде чем писать отчёт, разберись с находками в таком порядке:\n"
        "1. Если \"данные_отстают\" = true — последняя дата в данных отстаёт "
        "от ожидаемой (данные обычно догружаются по вчера включительно, "
        "\"сегодня\" в анализ никогда не попадает), и падения revenue/plan "
        "почти наверняка вызваны сбоем пайплайна загрузки, а не реальной "
        "проблемой. В этом случае одной фразой скажи это в начале отчёта и "
        "не описывай такие находки как тревожные (кратко упомяни фактом, без "
        "драматизации, либо вообще опусти, если они тривиально объясняются "
        "отставанием данных).\n"
        "2. Находки со значениями вроде inf/nan/бесконечности или числом, "
        "которое на порядки (в 100+ раз) больше типичной выручки "
        "направления — это ошибка в данных (например, деление на ноль или "
        "баг в источнике), а не бизнес-сигнал. Не подавай их как реальную "
        "аномалию — либо пропусти, либо вынеси отдельной короткой пометкой "
        "\"похоже на ошибку в данных, стоит проверить источник\".\n"
        "3. Из оставшихся реальных находок расставь приоритет по объёму в "
        "рублях и по силе отклонения (%, z-score, п.п.) — а не по порядку в "
        "JSON.\n"
        "4. Если несколько находок логически связаны (например, просела "
        "выручка по SKU и у него же критичный остаток на складе) — объедини "
        "их в один пункт с причинно-следственной связью вместо двух отдельных "
        "строк.\n\n"
        "Формат ответа:\n"
        "- по-русски, Telegram Markdown (*bold* только для ключевых цифр, не "
        "перебарщивай с форматированием);\n"
        "- 1-2 предложения общего вывода в начале — что сегодня важнее всего;\n"
        "- дальше группировка по смыслу (не обязательно строго по разделам "
        "JSON, если находки логичнее сгруппировать по причине) — по 1 строке "
        "на находку, важное сверху;\n"
        "- раздел/находки без данных просто не упоминай;\n"
        "- если существенных находок нет вообще (или все объясняются "
        "неполным днём/ошибкой в данных) — так и напиши одним предложением;\n"
        "- без вступлений, извинений и мета-комментариев о процессе анализа — "
        "сразу отчёт.\n\n"
        f"Данные:\n{json.dumps(findings, ensure_ascii=False, indent=2, default=str)}"
    )
    try:
        base_url = os.environ.get("ANTHROPIC_BASE_URL")  # опц.: прокси-эндпоинт вместо api.anthropic.com
        client = anthropic.Anthropic(api_key=api_key, base_url=base_url) if base_url else anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as exc:  # noqa: BLE001
        print(f"Вызов Claude не удался ({exc}), использую шаблон без LLM", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def split_into_chunks(text: str, max_len: int) -> list[str]:
    """Режет текст на части по границам строк, чтобы уложиться в лимит
    Telegram (4096 символов на сообщение). Если попадается одна строка
    длиннее max_len (в обычном отчёте не должно случиться — все строки это
    короткие пункты списка), она режется жёстко по max_len, чтобы отправка
    не упала с ошибкой Telegram API."""
    if len(text) <= max_len:
        return [text]
    chunks, current, length = [], [], 0
    for line in text.split("\n"):
        if len(line) > max_len:
            if current:
                chunks.append("\n".join(current))
                current, length = [], 0
            for i in range(0, len(line), max_len):
                chunks.append(line[i : i + max_len])
            continue
        if length + len(line) + 1 > max_len and current:
            chunks.append("\n".join(current))
            current, length = [], 0
        current.append(line)
        length += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def send_telegram_message(text: str, token: str, chat_id: str, reply_markup: dict | None = None) -> None:
    """reply_markup (опц.) — например, постоянная клавиатура-меню (см.
    telegram_bot.py); прикрепляется только к последнему чанку, чтобы не
    дублировать её в каждом сообщении при разбивке длинного текста."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks = split_into_chunks(text, TELEGRAM_MAX_LEN)
    for i, chunk in enumerate(chunks):
        payload = {"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"}
        if reply_markup is not None and i == len(chunks) - 1:
            payload["reply_markup"] = reply_markup
        resp = requests.post(url, json=payload, timeout=30)
        if resp.status_code != 200:
            # Текст может содержать "битый" Markdown (непарные * _ ` [ ] —
            # например, произвольный текст исключения). Telegram в этом
            # случае отвечает 400 "can't parse entities" — не должны терять
            # сообщение из-за этого, повторяем без parse_mode.
            payload.pop("parse_mode", None)
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code != 200:
                raise RuntimeError(f"Telegram API [{resp.status_code}]: {resp.text}")


def send_telegram_photo(photo_bytes: bytes, token: str, chat_id: str, caption: "str | None" = None) -> None:
    """Отправляет PNG (build_kpi_chart_png()) через sendPhoto. Без parse_mode —
    caption у Telegram ограничен 1024 символами (в отличие от 4096 у обычного
    сообщения), поэтому основной текст отчёта всегда шлём отдельным
    send_telegram_message() следом, а не пытаемся впихнуть его в caption."""
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    files = {"photo": ("chart.png", photo_bytes, "image/png")}
    data = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption[:1024]
    resp = requests.post(url, data=data, files=files, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Telegram API [{resp.status_code}]: {resp.text}")


# ---------------------------------------------------------------------------

def build_kpi_chart_png(df: pd.DataFrame) -> "bytes | None":
    """PNG с двумя рядами по дням — выручка (столбцы) и расходы на рекламу
    (линия) — по всем МП/направлениям вместе, за то же окно, что и остальные
    находки в build_daily_report(). Возвращает None, если matplotlib не
    установлен или данных недостаточно для графика — вызывающий код (main(),
    telegram_bot.py) должен просто пропустить отправку картинки в этом случае,
    отчёт не должен падать из-за отсутствующей опциональной зависимости."""
    if not _HAS_MATPLOTLIB or df.empty:
        return None
    daily = (
        df.groupby("Date")
        .agg(revenue=(REVENUE_COL, "sum"), ad_spend=(AD_SPEND_COL, "sum"))
        .reset_index()
        .sort_values("Date")
    )
    if len(daily) < 2:
        return None
    try:
        fig, ax1 = plt.subplots(figsize=(8, 4))
        ax1.bar(daily["Date"], daily["revenue"], color="#4C72B0", label="Выручка, ₽")
        ax1.set_ylabel("Выручка, ₽")
        ax1.tick_params(axis="x", rotation=45)
        ax2 = ax1.twinx()
        ax2.plot(daily["Date"], daily["ad_spend"], color="#C44E52", marker="o", linewidth=1.5, label="Реклама, ₽")
        ax2.set_ylabel("Расходы на рекламу, ₽")
        fig.suptitle("Выручка и расходы на рекламу по дням")
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=8)
        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=110)
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        print(f"Не удалось построить график ({exc}), пропускаю", file=sys.stderr)
        return None


def build_daily_report(engine) -> "tuple[str, bytes | None]":
    """Загружает данные, считает аномалии и собирает (текст отчёта, PNG-график
    или None) — без отправки в Telegram. Используется и cron-режимом (main(),
    ниже), и интерактивным ботом (telegram_bot.py), чтобы не дублировать
    логику. build_report_text() ниже — тонкая обёртка для обратной
    совместимости (например, для смок-тестов), возвращает только текст."""
    lookback_days = int(os.environ.get("ANOMALY_LOOKBACK_DAYS", 35))
    pct_threshold = float(os.environ.get("ANOMALY_PCT_THRESHOLD", 20))
    z_threshold = float(os.environ.get("ANOMALY_Z_THRESHOLD", 2.0))
    min_revenue = float(os.environ.get("MIN_REVENUE_FOR_CHECK", 500))
    drr_pp_threshold = float(os.environ.get("DRR_PP_THRESHOLD", 10))
    stock_low_qty = float(os.environ.get("STOCK_LOW_QTY", 5))
    low_days_threshold = float(os.environ.get("STOCK_LOW_DAYS", 5))
    plan_pct_threshold = float(os.environ.get("PLAN_PACE_THRESHOLD_PCT", 15))
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

    df = load_marketplace_data(engine, lookback_days)
    if df.empty:
        raise RuntimeError("v_marketplaces_full пуста за выбранный период — нечего анализировать")
    try:
        stock_df = load_stock_data(engine)
    except Exception as exc:  # noqa: BLE001
        print(f"    предупреждение: не удалось прочитать остатки склада ({exc})", file=sys.stderr)
        stock_df = pd.DataFrame(columns=["Дата", "SKU", "Склад", "Доступно", "Заказано"])
    last_date = df["Date"].max()
    # load_marketplace_data() уже режет данные по "вчера" включительно —
    # "сегодня" сюда физически не попадает (см. комментарий в самой функции).
    # Остаётся другой сценарий: пайплайн отстаёт СИЛЬНЕЕ, чем на 1 день
    # (последняя дата в данных — позавчера и раньше) — это уже похоже на сбой
    # загрузки, а не на нормальный суточный лаг. Передаём сигнал дальше в
    # LLM/шаблон, чтобы связанные просадки revenue/plan не подавались как
    # реальная бизнес-проблема.
    expected_last_date = pd.Timestamp.today().normalize() - pd.Timedelta(days=1)
    is_data_stale = last_date.normalize() < expected_last_date

    findings = {
        "дата": str(last_date.date()),
        "данные_отстают": is_data_stale,
        "revenue": detect_revenue_anomalies(df, pct_threshold, z_threshold, min_revenue),
        "sku_movers": detect_sku_top_movers(df),
        "drr": detect_drr_anomalies(df, drr_pp_threshold),
        "stock": detect_stock_anomalies(stock_df, stock_low_qty),
        "low_days": detect_low_days_of_stock(df, low_days_threshold),
        "plan": detect_plan_pace(df, plan_pct_threshold),
    }
    total = sum(len(v) for k, v in findings.items() if isinstance(v, list))
    print(f"    найдено сигналов: {total}")

    text = summarize_with_llm(findings, model) or render_fallback_text(findings)
    chart = build_kpi_chart_png(df)
    return text, chart


def build_report_text(engine) -> str:
    """Обёртка над build_daily_report() для обратной совместимости — только
    текст, без графика (используется там, где график не нужен, например в
    смок-тестах)."""
    text, _chart = build_daily_report(engine)
    return text


def main():
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not telegram_token or not telegram_chat_id:
        raise RuntimeError("Не заданы переменные окружения TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")

    print("1/4: подключаюсь к Postgres...")
    engine = get_postgres_engine()

    print("2/4: загружаю данные и считаю аномалии...")
    text, chart = build_daily_report(engine)

    print("3/4: отправляю в Telegram...")
    if chart:
        try:
            send_telegram_photo(chart, telegram_token, telegram_chat_id)
        except Exception as exc:  # noqa: BLE001
            print(f"    предупреждение: не удалось отправить график ({exc})", file=sys.stderr)
    send_telegram_message(text, telegram_token, telegram_chat_id)
    print("4/4: готово.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка: {exc}", file=sys.stderr)
        sys.exit(1)
