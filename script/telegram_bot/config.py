# -- coding: utf-8 --
"""
Конфигурация Telegram-бота.

Секреты берём из telegram_bot/.env (см. .env.example) либо из переменных окружения.
Специально не используем python-dotenv, чтобы не тянуть лишнюю зависимость
в окружения, где её нет (main.py, main_ozon.py и т.д. используют requirements.txt
без dotenv).
"""

import os

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
_ENV_FILE = os.path.join(_THIS_DIR, '.env')


def _load_dotenv(path):
    if not os.path.isfile(path):
        return
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


_load_dotenv(_ENV_FILE)

# ─── Telegram ──────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')

# Чат, куда шлём уведомления об успехе/ошибках (id пользователя или группы)
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

# Кому разрешено писать боту команды и загружать cookies.json (список id через запятую)
TELEGRAM_ALLOWED_USER_IDS = {
    int(x) for x in os.environ.get('TELEGRAM_ALLOWED_USER_IDS', '').replace(' ', '').split(',') if x
}

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Прокси только для запросов к Telegram API (например локальный Xray/V2Ray),
# остальной код (БД, wb/ozon/ya API) прокси не использует.
# Пример: socks5h://127.0.0.1:10808 или http://127.0.0.1:10809
TELEGRAM_PROXY_URL = os.environ.get('TELEGRAM_PROXY_URL', '')
TELEGRAM_PROXIES = {'http': TELEGRAM_PROXY_URL, 'https': TELEGRAM_PROXY_URL} if TELEGRAM_PROXY_URL else None

# ─── Задачи, которые можно запускать вручную из бота ────────────────────────
# key -> (человекочитаемое имя, путь к скрипту относительно корня проекта, рабочая директория относительно корня)
JOBS = {
    'wb':            ('Wildberries → БД',        'main.py',                                  '.'),
    'ozon':          ('Ozon → БД',               'main_ozon.py',                             '.'),
    'yandex':        ('Yandex → БД',              'main_yandex.py',                           '.'),
    'files':         ('Файлы отчётов → БД',       'main_files.py',                            '.'),
    'ozon_tx':       ('Ozon транзакции (cookies)', 'ozon_sync.py',                            'ozon_transaction'),
    'ozon_advert':   ('Ozon реклама (cookies)',    'ozon_advert_sync.py',                     'ozon_transaction'),
}

# Куда сохранять cookies.json, присланный документом в чат
COOKIES_FILE_PATH = os.path.join(_PROJECT_ROOT, 'ozon_transaction', 'cookies.json')

PROJECT_ROOT = _PROJECT_ROOT
