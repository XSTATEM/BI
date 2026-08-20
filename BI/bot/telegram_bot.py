"""
Интерактивный Telegram-бот: слушает входящие сообщения (long polling через
getUpdates) и по запросу присылает нужный раздел анализа — прямо в тот чат,
откуда пришёл запрос.

В отличие от daily_sales_report.py, здесь НЕ нужен TELEGRAM_CHAT_ID заранее —
чат определяется из входящего сообщения. Это отдельный, постоянно работающий
процесс (не cron): он висит и ждёт сообщений, пока не остановлен.

Команды и кнопки меню (постоянная клавиатура внизу экрана — MENU_KEYBOARD,
отправляется вместе с любым ответом бота и остаётся видна, is_persistent):
  /start, /help              — короткая подсказка + показать клавиатуру
  📊 Продажи, /report,
    любой нераспознанный текст — build_daily_report() (аномалии/план/остатки),
                                  без выбора периода (детекторы всегда
                                  смотрят на ANOMALY_LOOKBACK_DAYS); если
                                  получилось построить график (KPI-график,
                                  matplotlib) — сначала отправляется PNG
                                  (send_telegram_photo), затем текст. "Сегодня"
                                  никогда не анализируется — данные приходят
                                  с задержкой ~1 день (см. load_marketplace_data
                                  в daily_sales_report.py).
  📢 Реклама, 💰 Финансы, 💸 Расходы, 🔗 Зависимости, 🧩 Паттерны — все пять
    поддерживают выбор периода в два шага и агрегацию по "Направление":
      1. пользователь нажимает кнопку раздела;
      2. бот показывает PERIOD_KEYBOARD ("7 дней"/"14 дней"/"30 дней"/
         "Свой период"); пресет запускает отчёт сразу, "Свой период" просит
         ввести даты текстом (ДД.ММ.ГГГГ-ДД.ММ.ГГГГ, год можно не указывать —
         возьмётся текущий), затем запускает отчёт с этим диапазоном.
    Состояние ожидания периода хранится в памяти процесса (pending_period,
    per chat_id) — переживает только пока бот работает; "отмена" в любой
    момент возвращает к обычной клавиатуре без запуска отчёта.
  🔍 Сверка — отдельный флоу в три шага (маркетплейс -> номер недели ->
    направление), см. pending_reconciliation_mp/_week/_direction ниже;
    отдаёт сумму выручки по выкупам, маржу и расходы на рекламу за неделю.

Вся аналитика (детекторы, пороги, тексты) — в daily_sales_report.py, этот
файл только слушает Telegram, роутит текст кнопки/период на нужную
build_*_report_text(engine, period) и показывает клавиатуру.

Переменные окружения:
  Postgres:      PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD, PGSCHEMA
                 (те же, что и в pbi_to_postgres.py / daily_sales_report.py)
  Telegram:      TELEGRAM_BOT_TOKEN — токен бота от @BotFather (обязателен)
                 TELEGRAM_ALLOWED_CHAT_IDS — опц., через запятую: если
                    задано, бот отвечает только этим chat_id, остальных
                    игнорирует (иначе отвечает любому, кто напишет — открытый
                    доступ к вашим данным о продажах, задайте это в проде)
  LLM (опц.):    ANTHROPIC_API_KEY, ANTHROPIC_MODEL, ANTHROPIC_BASE_URL —
                 те же, что в daily_sales_report.py; без ключа — шаблон
                 (используется только в build_daily_report(); остальные шесть
                 разделов — детерминированные шаблоны, без LLM)
  Пороги (опц.) — все переменные из daily_sales_report.py: ANOMALY_*,
                 DRR_PP_THRESHOLD, STOCK_LOW_*, PLAN_PACE_THRESHOLD_PCT,
                 AD_REPORT_PERIOD_DAYS, FIN_REPORT_PERIOD_DAYS,
                 EXPENSE_REPORT_PERIOD_DAYS, CORR_LOOKBACK_DAYS, CORR_MIN_ABS,
                 PATTERN_LOOKBACK_DAYS, PATTERN_WEEKDAY_PCT,
                 PATTERN_TREND_RHO, PATTERN_MIN_WEEKDAY_SAMPLES,
                 PATTERN_MIN_WEEKS — см. докстринг daily_sales_report.py
  POLL_TIMEOUT_SEC — опц. (по умолчанию 30) — long-poll таймаут на стороне
                 Telegram для getUpdates

Запуск (процесс должен работать постоянно, не через cron):
    TELEGRAM_BOT_TOKEN=... PGHOST=... PGDATABASE=... PGUSER=... PGPASSWORD=... \\
        python telegram_bot.py

Для автозапуска и перезапуска при падении — см. README, пример systemd unit.
"""

import os
import re
import sys
import time

import requests

from daily_sales_report import (
    RECONCILIATION_MARKETPLACES,
    Period,
    build_ads_report_text,
    build_correlation_report_text,
    build_daily_report,
    build_expenses_report_text,
    build_finance_report_text,
    build_patterns_report_text,
    build_reconciliation_report_text,
    list_directions_for_week,
    parse_custom_period_text,
    send_telegram_message,
    send_telegram_photo,
)
from pbi_to_postgres import get_postgres_engine

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_RAW = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS")
ALLOWED_IDS = {x.strip() for x in ALLOWED_RAW.split(",") if x.strip()} if ALLOWED_RAW else None
POLL_TIMEOUT = int(os.environ.get("POLL_TIMEOUT_SEC", 30))

# Постоянная клавиатура внизу экрана Telegram (resize_keyboard — компактный
# размер кнопок, is_persistent — не скрывается после нажатия/отправки).
MENU_KEYBOARD = {
    "keyboard": [
        ["📊 Продажи", "📢 Реклама"],
        ["💰 Финансы", "💸 Расходы"],
        ["🔗 Зависимости", "🧩 Паттерны"],
        ["🔍 Сверка"],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

# Клавиатура выбора маркетплейса для 🔍 Сверка — ровно эти три значения
# использует join_marketplaces.sql в колонке "Маркетплейс" (см.
# RECONCILIATION_MARKETPLACES в daily_sales_report.py).
RECONCILE_MP_KEYBOARD = {
    "keyboard": [RECONCILIATION_MARKETPLACES, ["⬅️ Отмена"]],
    "resize_keyboard": True,
}

# Клавиатура выбора периода — показывается после кнопки раздела из
# PERIOD_REPORT_HANDLERS (см. ниже). Не is_persistent — это временный шаг,
# после выбора периода снова показывается MENU_KEYBOARD.
PERIOD_KEYBOARD = {
    "keyboard": [
        ["7 дней", "14 дней", "30 дней"],
        ["Свой период"],
        ["⬅️ Отмена"],
    ],
    "resize_keyboard": True,
}
PERIOD_PRESETS = {"7 дней": 7, "14 дней": 14, "30 дней": 30}

# Разделы, где build_*_report_text(engine, period) принимает Period — для них
# кнопка сначала открывает PERIOD_KEYBOARD, а не запускает отчёт сразу.
PERIOD_REPORT_HANDLERS = {
    "📢 реклама": build_ads_report_text,
    "💰 финансы": build_finance_report_text,
    "💸 расходы": build_expenses_report_text,
    "🔗 зависимости": build_correlation_report_text,
    "🧩 паттерны": build_patterns_report_text,
}

# chat_id -> ключ из PERIOD_REPORT_HANDLERS: ждём, когда пользователь выберет
# пресет периода или "Свой период" на PERIOD_KEYBOARD.
pending_period: dict[str, str] = {}
# chat_id -> ключ из PERIOD_REPORT_HANDLERS: ждём ввод дат текстом после
# "Свой период". Раздельно от pending_period, чтобы не путать два шага.
pending_custom_dates: dict[str, str] = {}

# 🔍 Сверка — состояние из трёх шагов (МП -> номер недели -> направление),
# аналогично pending_period/pending_custom_dates выше, только на один шаг
# больше. Раздельные dict'ы на каждый шаг, чтобы не путать, чего именно мы
# ждём от пользователя.
pending_reconciliation_mp: set = set()
# chat_id -> маркетплейс (ждём номер недели текстом)
pending_reconciliation_week: dict[str, str] = {}
# chat_id -> {"marketplace":.., "week":.., "directions": [...]} (ждём выбор
# направления или "Все направления")
pending_reconciliation_direction: dict[str, dict] = {}

HELP_TEXT = (
    "Привет! Выберите раздел на клавиатуре ниже — пришлю анализ:\n"
    "📊 Продажи — аномалии выручки, план недели, остатки\n"
    "📢 Реклама — расход на продвижение, ДРР, ROAS\n"
    "💰 Финансы — маржа, дебиторка\n"
    "💸 Расходы — разбивка по статьям расходов\n"
    "🔗 Зависимости — корреляции между метриками\n"
    "🧩 Паттерны — сезонность по дням недели и устойчивые тренды\n"
    "🔍 Сверка — выручка/маржа/реклама по маркетплейсу и номеру недели\n\n"
    "Для 📢/💰/💸/🔗/🧩 после нажатия кнопки спрошу период "
    "(7/14/30 дней или свои даты). Для 🔍 Сверка спрошу маркетплейс, номер "
    "недели и (опционально) направление."
)

CUSTOM_PERIOD_PROMPT = (
    "Введите период в формате ДД.ММ.ГГГГ-ДД.ММ.ГГГГ "
    "(например, 01.07.2026-15.07.2026; год можно не указывать — возьмётся текущий). "
    "Или напишите «отмена»."
)

WEEK_NUMBER_PROMPT = "Введите номер недели (например, 27). Или напишите «отмена»."


def build_direction_keyboard(directions: list) -> dict:
    """Клавиатура выбора направления для шага 3 Сверки — "Все направления"
    отдельной строкой сверху, затем найденные направления по 2 в ряд."""
    rows = [["Все направления"]]
    for i in range(0, len(directions), 2):
        rows.append(directions[i : i + 2])
    rows.append(["⬅️ Отмена"])
    return {"keyboard": rows, "resize_keyboard": True}


def parse_week_number(text: str) -> "int | None":
    m = re.search(r"\d{1,2}", text or "")
    if not m:
        return None
    n = int(m.group())
    return n if 1 <= n <= 53 else None


def api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"


def get_updates(offset=None):
    params = {"timeout": POLL_TIMEOUT}
    if offset is not None:
        params["offset"] = offset
    resp = requests.get(api_url("getUpdates"), params=params, timeout=POLL_TIMEOUT + 15)
    resp.raise_for_status()
    return resp.json().get("result", [])


def reply(chat_id, text: str, keyboard: dict | None = MENU_KEYBOARD) -> None:
    send_telegram_message(text, TELEGRAM_TOKEN, chat_id, reply_markup=keyboard)


def clear_pending(chat_id) -> None:
    pending_period.pop(chat_id, None)
    pending_custom_dates.pop(chat_id, None)
    pending_reconciliation_mp.discard(chat_id)
    pending_reconciliation_week.pop(chat_id, None)
    pending_reconciliation_direction.pop(chat_id, None)


def run_period_report(chat_id, report_key: str, period: Period) -> None:
    handler = PERIOD_REPORT_HANDLERS[report_key]
    print(f"Запрос отчёта ({handler.__name__}, период={period}) от chat_id={chat_id}")
    try:
        engine = get_postgres_engine()
        report_text = handler(engine, period)
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка при сборе отчёта: {exc}", file=sys.stderr)
        reply(chat_id, f"Не получилось собрать отчёт: {exc}")
        return
    reply(chat_id, report_text)


def run_reconciliation_report(chat_id, marketplace: str, week_number: int, direction: str | None = None) -> None:
    print(
        f"Запрос сверки (marketplace={marketplace}, week={week_number}, "
        f"direction={direction}) от chat_id={chat_id}"
    )
    try:
        engine = get_postgres_engine()
        report_text = build_reconciliation_report_text(engine, marketplace, week_number, direction=direction)
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка при сборе сверки: {exc}", file=sys.stderr)
        reply(chat_id, f"Не получилось собрать сверку: {exc}")
        return
    reply(chat_id, report_text)


def handle_message(chat_id, text: str) -> None:
    normalized = (text or "").strip().lower()

    if normalized in ("/start", "/help"):
        clear_pending(chat_id)
        reply(chat_id, HELP_TEXT)
        return

    if normalized in ("отмена", "⬅️ отмена", "/cancel"):
        clear_pending(chat_id)
        reply(chat_id, "Ок, отменил. Выберите раздел на клавиатуре ниже.")
        return

    # Шаг 2: ждём выбор периода (после нажатия кнопки раздела из PERIOD_REPORT_HANDLERS).
    if chat_id in pending_period:
        report_key = pending_period[chat_id]
        preset_days = PERIOD_PRESETS.get((text or "").strip())
        if preset_days is not None:
            clear_pending(chat_id)
            run_period_report(chat_id, report_key, Period(days_back=preset_days))
            return
        if normalized == "свой период":
            pending_period.pop(chat_id, None)
            pending_custom_dates[chat_id] = report_key
            reply(chat_id, CUSTOM_PERIOD_PROMPT, keyboard=None)
            return
        # Текст не похож на выбор периода — не теряем ввод пользователя,
        # снимаем ожидание и обрабатываем как обычную команду ниже.
        clear_pending(chat_id)

    # Шаг 3: ждём ввод кастомных дат (после "Свой период").
    if chat_id in pending_custom_dates:
        report_key = pending_custom_dates[chat_id]
        period = parse_custom_period_text(text)
        if period is None:
            reply(chat_id, f"Не разобрал даты.\n{CUSTOM_PERIOD_PROMPT}", keyboard=None)
            return
        pending_custom_dates.pop(chat_id, None)
        run_period_report(chat_id, report_key, period)
        return

    # Шаг 2 Сверки: ждём выбор маркетплейса (после нажатия "🔍 Сверка").
    if chat_id in pending_reconciliation_mp:
        mp_match = next(
            (mp for mp in RECONCILIATION_MARKETPLACES if mp.lower() == (text or "").strip().lower()),
            None,
        )
        if mp_match is not None:
            pending_reconciliation_mp.discard(chat_id)
            pending_reconciliation_week[chat_id] = mp_match
            reply(chat_id, WEEK_NUMBER_PROMPT, keyboard=None)
            return
        # Не похоже на маркетплейс из клавиатуры — снимаем ожидание, обрабатываем как обычную команду.
        pending_reconciliation_mp.discard(chat_id)

    # Шаг 3 Сверки: ждём номер недели.
    if chat_id in pending_reconciliation_week:
        marketplace = pending_reconciliation_week[chat_id]
        week_number = parse_week_number(text)
        if week_number is None:
            reply(chat_id, f"Не разобрал номер недели.\n{WEEK_NUMBER_PROMPT}", keyboard=None)
            return
        pending_reconciliation_week.pop(chat_id, None)
        try:
            engine = get_postgres_engine()
            directions = list_directions_for_week(engine, marketplace, week_number)
        except Exception as exc:  # noqa: BLE001
            print(f"Ошибка при получении направлений: {exc}", file=sys.stderr)
            reply(chat_id, f"Не получилось получить направления: {exc}")
            return
        pending_reconciliation_direction[chat_id] = {
            "marketplace": marketplace,
            "week": week_number,
            "directions": directions,
        }
        reply(
            chat_id,
            "Выберите направление или «Все направления»:",
            keyboard=build_direction_keyboard(directions),
        )
        return

    # Шаг 4 Сверки: ждём выбор направления.
    if chat_id in pending_reconciliation_direction:
        state = pending_reconciliation_direction[chat_id]
        stripped = (text or "").strip()
        if stripped.lower() == "все направления":
            pending_reconciliation_direction.pop(chat_id, None)
            run_reconciliation_report(chat_id, state["marketplace"], state["week"], direction=None)
            return
        dir_match = next((d for d in state["directions"] if d.lower() == stripped.lower()), None)
        if dir_match is not None:
            pending_reconciliation_direction.pop(chat_id, None)
            run_reconciliation_report(chat_id, state["marketplace"], state["week"], direction=dir_match)
            return
        # Не похоже на направление из клавиатуры — снимаем ожидание, обрабатываем как обычную команду.
        pending_reconciliation_direction.pop(chat_id, None)

    # Шаг 1: кнопка раздела с выбором периода — сначала спрашиваем период.
    if normalized in PERIOD_REPORT_HANDLERS:
        pending_period[chat_id] = normalized
        reply(chat_id, "За какой период?", keyboard=PERIOD_KEYBOARD)
        return

    # 🔍 Сверка — шаг 1: спрашиваем маркетплейс.
    if normalized == "🔍 сверка":
        pending_reconciliation_mp.add(chat_id)
        reply(chat_id, "Выберите маркетплейс:", keyboard=RECONCILE_MP_KEYBOARD)
        return

    # 📊 Продажи / /report / нераспознанный текст — без периода, как раньше.
    print(f"Запрос отчёта (build_daily_report) от chat_id={chat_id}: {text!r}")
    try:
        engine = get_postgres_engine()
        report_text, chart_png = build_daily_report(engine)
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка при сборе отчёта: {exc}", file=sys.stderr)
        reply(chat_id, f"Не получилось собрать отчёт: {exc}")
        return
    if chart_png:
        try:
            send_telegram_photo(chart_png, TELEGRAM_TOKEN, chat_id)
        except Exception as exc:  # noqa: BLE001
            print(f"Ошибка при отправке графика: {exc}", file=sys.stderr)
    reply(chat_id, report_text)


def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("Не задана переменная окружения TELEGRAM_BOT_TOKEN")

    print("Бот запущен, жду сообщений (Ctrl+C для остановки)...")
    offset = None
    while True:
        try:
            updates = get_updates(offset)
        except Exception as exc:  # noqa: BLE001
            print(f"Ошибка getUpdates: {exc}", file=sys.stderr)
            time.sleep(5)
            continue

        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("channel_post")
            if not msg:
                continue
            chat_id = str(msg["chat"]["id"])
            if ALLOWED_IDS and chat_id not in ALLOWED_IDS:
                print(f"Игнорирую сообщение от неразрешённого chat_id={chat_id}")
                continue
            handle_message(chat_id, msg.get("text"))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nОстановлено.")
