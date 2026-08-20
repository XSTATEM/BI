# -- coding: utf-8 --
"""
Telegram-бот для управления выгрузками.

Умеет:
  - присылать уведомления об успехе/ошибках выгрузки (шлют сами скрипты через notifier.py)
  - принимать cookies.json файлом в чате и сохранять его в ozon_transaction/cookies.json
  - запускать выгрузки вручную командой /run <job>

Запуск (постоянно работающий процесс, не cron):
    python3 telegram_bot/bot.py

Для автозапуска на сервере см. telegram_bot/README.md (systemd unit).
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram_bot.config import (
    TELEGRAM_API_URL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_ALLOWED_USER_IDS,
    TELEGRAM_PROXIES,
    JOBS,
    COOKIES_FILE_PATH,
    PROJECT_ROOT,
)
from telegram_bot.notifier import send_message

logging.basicConfig(
    format='[%(asctime)s] [%(levelname)s] => %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO,
)
log = logging.getLogger(__name__)

OFFSET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.offset')


def _read_offset():
    if os.path.isfile(OFFSET_FILE):
        try:
            with open(OFFSET_FILE, 'r') as f:
                return int(f.read().strip())
        except (ValueError, OSError):
            return None
    return None


def _write_offset(offset):
    with open(OFFSET_FILE, 'w') as f:
        f.write(str(offset))


def is_allowed(user_id):
    return user_id in TELEGRAM_ALLOWED_USER_IDS


def jobs_list_text():
    lines = ["📋 <b>Доступные задачи</b>"]
    for key, (name, _script, _cwd) in JOBS.items():
        lines.append(f"• <code>{key}</code> — {name}")
    return "\n".join(lines)


def help_text():
    return (
        "🤖 <b>Команды</b>\n\n"
        "📊 /status — состояние выгрузок\n"
        "▶️ /run &lt;job&gt; — запустить выгрузку вручную\n"
        "📋 /jobs — список доступных задач\n\n"
        "🍪 <b>Обновить cookies.json</b>\n"
        "• пришли файл cookies.json сюда, или\n"
        "• пришли текстом путь к файлу на сервере, например:\n"
        "  <code>/home/user/cookies.json</code>\n\n"
        + jobs_list_text()
    )


def run_job(key, chat_id):
    name, script, cwd_rel = JOBS[key]
    cwd_abs = os.path.join(PROJECT_ROOT, cwd_rel)
    script_path = os.path.join(cwd_abs, script)
    if not os.path.isfile(script_path):
        send_message(f"⚠️ Не найден скрипт для <b>{name}</b>: {script_path}", chat_id=chat_id)
        return

    send_message(f"🚀 Запускаю <b>{name}</b>...", chat_id=chat_id)
    log.info(f"Manual run requested: {key} ({script_path})")

    def _worker():
        try:
            result = subprocess.run(
                [sys.executable, script],
                cwd=cwd_abs,
                capture_output=True,
                text=True,
                timeout=60 * 60 * 3,
            )
            if result.returncode != 0:
                tail = (result.stderr or result.stdout or '').strip()[-1500:]
                send_message(
                    f"⚠️ <b>{name}</b> завершился с кодом {result.returncode}.\n"
                    f"Проверь лог. Ожидай отдельное уведомление от самого скрипта, если оно настроено.\n\n"
                    f"<code>{tail}</code>",
                    chat_id=chat_id,
                )
        except subprocess.TimeoutExpired:
            send_message(f"⚠️ <b>{name}</b>: превышено время ожидания (3ч), процесс остановлен", chat_id=chat_id)
        except Exception as e:
            send_message(f"⚠️ Не удалось запустить <b>{name}</b>: {e}", chat_id=chat_id)

    threading.Thread(target=_worker, daemon=True).start()


def status_text():
    lines = ["📊 <b>Статус выгрузок</b>", ""]
    for key, (name, script, cwd_rel) in JOBS.items():
        cwd_abs = os.path.join(PROJECT_ROOT, cwd_rel)
        log_candidates = [
            os.path.join(PROJECT_ROOT, f"log_{os.path.splitext(script)[0]}.txt"),
            os.path.join(cwd_abs, f"log_{os.path.splitext(script)[0]}.txt"),
        ]
        log_path = next((p for p in log_candidates if os.path.isfile(p)), None)
        if log_path:
            mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(log_path)))
            lines.append(f"✅ <code>{key}</code> — {name}\n     последний лог: {mtime}")
        else:
            lines.append(f"⚠️ <code>{key}</code> — {name}\n     лог не найден")

    lines.append("")
    if os.path.isfile(COOKIES_FILE_PATH):
        mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(COOKIES_FILE_PATH)))
        lines.append(f"🍪 cookies.json обновлён: {mtime}")
    else:
        lines.append("⚠️ cookies.json отсутствует")
    return "\n".join(lines)


def _save_cookies(content, chat_id, user_id, source_desc):
    try:
        json.loads(content.decode('utf-8'))
    except Exception as e:
        send_message(f"❌ Файл не похож на валидный JSON: {e}", chat_id=chat_id)
        return

    os.makedirs(os.path.dirname(COOKIES_FILE_PATH), exist_ok=True)
    with open(COOKIES_FILE_PATH, 'wb') as f:
        f.write(content)

    log.info(f"cookies.json updated by user {user_id} from {source_desc}")
    send_message(
        f"✅ <b>cookies.json обновлён</b>\n"
        f"Источник: {source_desc}\n"
        f"Сохранено в: <code>{COOKIES_FILE_PATH}</code>",
        chat_id=chat_id,
    )


def handle_document(message, chat_id, user_id):
    if not is_allowed(user_id):
        send_message(f"⛔ Доступ запрещён. Ваш id: <code>{user_id}</code>", chat_id=chat_id)
        return

    document = message['document']
    file_name = document.get('file_name', '')
    if not file_name.lower().endswith('.json'):
        send_message("Пришли файл с расширением .json (cookies.json)", chat_id=chat_id)
        return

    file_id = document['file_id']
    resp = requests.get(f"{TELEGRAM_API_URL}/getFile", params={'file_id': file_id}, proxies=TELEGRAM_PROXIES, timeout=15)
    resp.raise_for_status()
    file_path = resp.json()['result']['file_path']

    file_resp = requests.get(
        f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}",
        proxies=TELEGRAM_PROXIES,
        timeout=30,
    )
    file_resp.raise_for_status()

    _save_cookies(file_resp.content, chat_id, user_id, f"загруженный файл «{file_name}»")


def handle_cookie_path(path, chat_id, user_id):
    if not is_allowed(user_id):
        send_message(f"⛔ Доступ запрещён. Ваш id: <code>{user_id}</code>", chat_id=chat_id)
        return

    if not os.path.isfile(path):
        send_message(f"❌ Файл не найден на сервере: <code>{path}</code>", chat_id=chat_id)
        return

    with open(path, 'rb') as f:
        content = f.read()

    _save_cookies(content, chat_id, user_id, f"файл на сервере <code>{path}</code>")


def handle_command(text, chat_id, user_id):
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lower().split('@')[0]
    arg = parts[1].strip() if len(parts) > 1 else ''

    if cmd in ('/start', '/help'):
        send_message(help_text(), chat_id=chat_id)
        if not is_allowed(user_id):
            send_message(
                f"🔑 Ваш id: <code>{user_id}</code>\n"
                "Он не в списке разрешённых — команды /run, /status и обновление cookies.json недоступны.",
                chat_id=chat_id,
            )
        return

    if cmd == '/jobs':
        send_message(jobs_list_text(), chat_id=chat_id)
        return

    if cmd == '/status':
        if not is_allowed(user_id):
            send_message(f"⛔ Доступ запрещён. Ваш id: <code>{user_id}</code>", chat_id=chat_id)
            return
        send_message(status_text(), chat_id=chat_id)
        return

    if cmd == '/run':
        if not is_allowed(user_id):
            send_message(f"⛔ Доступ запрещён. Ваш id: <code>{user_id}</code>", chat_id=chat_id)
            return
        key = arg.lower()
        if key not in JOBS:
            send_message(f"🤔 Неизвестная задача <code>{key}</code>.\n\n{jobs_list_text()}", chat_id=chat_id)
            return
        run_job(key, chat_id)
        return

    send_message("🤔 Не знаю такую команду. /help — список команд.", chat_id=chat_id)


def process_update(update):
    message = update.get('message') or update.get('edited_message')
    if not message:
        return

    chat_id = message['chat']['id']
    user_id = message['from']['id']

    if 'document' in message:
        handle_document(message, chat_id, user_id)
        return

    text = message.get('text', '')
    text = text.strip() if text else ''
    if not text:
        return

    # текстом присланный абсолютный путь к .json на сервере -> обновление cookies.json
    if text.startswith('/') and text.lower().endswith('.json'):
        handle_cookie_path(text, chat_id, user_id)
        return

    if text.startswith('/'):
        handle_command(text, chat_id, user_id)


def main():
    if not TELEGRAM_BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN не задан. Заполни telegram_bot/.env (см. .env.example)")
        sys.exit(1)

    if not TELEGRAM_ALLOWED_USER_IDS:
        log.warning("TELEGRAM_ALLOWED_USER_IDS пуст — никто не сможет использовать /run и загрузку cookies.json")

    log.info("Telegram bot started, polling...")
    offset = _read_offset()

    while True:
        try:
            params = {'timeout': 30}
            if offset is not None:
                params['offset'] = offset
            resp = requests.get(f"{TELEGRAM_API_URL}/getUpdates", params=params, proxies=TELEGRAM_PROXIES, timeout=35)
            resp.raise_for_status()
            updates = resp.json().get('result', [])

            for update in updates:
                offset = update['update_id'] + 1
                try:
                    process_update(update)
                except Exception as e:
                    log.exception(f"Error processing update: {e}")
                _write_offset(offset)

        except requests.exceptions.RequestException as e:
            log.warning(f"Network error polling Telegram: {e}")
            time.sleep(5)
        except Exception as e:
            log.exception(f"Unexpected error in polling loop: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
