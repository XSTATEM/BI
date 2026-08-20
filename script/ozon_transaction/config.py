"""
Конфигурация: кабинеты Ozon и подключение к PostgreSQL
Все секреты берём из .env файла
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── Кабинеты Ozon ────────────────────────────────────────────────────────────
# client_id → название (используется как метка в БД и в логах)
ACCOUNTS = {
    "4127310": "семейные_ценности",
    "4394450": "платформа_продаж",
    "4112310": "безикейность",
    "487010": "Ечипс Импорт"
    # "XXXXXXX": "четвертый_кабинет",  # добавь 4-й
}

# ─── PostgreSQL ───────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host":     os.getenv("DB_HOST"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "dbname":   os.getenv("DB_NAME"),
    "user":     os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD", ""),
}

TABLE_NAME = "ozon_transactioon_csv"   # имя таблицы в БД

# ─── Ozon endpoint ────────────────────────────────────────────────────────────
OZON_URL = (
    "https://seller.ozon.ru/api/site/self-gateway"
    "/api/accruals/reports/download"
)

# ─── Файлы ────────────────────────────────────────────────────────────────────
COOKIES_FILE = "cookies.json"   # хранилище cookies (рядом со скриптом)
TEMP_DIR     = "/tmp/ozon_reports"  # временная папка для xlsx файлов
