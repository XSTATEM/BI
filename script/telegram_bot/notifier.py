# -- coding: utf-8 --
"""
Отправка уведомлений в Telegram из скриптов выгрузки (main.py, main_ozon.py, ...).

Специально не поднимает исключений наружу: если бот не настроен или Telegram
недоступен, выгрузка не должна из-за этого падать.
"""

import datetime
import logging

import requests

from telegram_bot.config import TELEGRAM_API_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_PROXIES

log = logging.getLogger(__name__)


def send_message(text, chat_id=None):
    if not TELEGRAM_BOT_TOKEN or not (chat_id or TELEGRAM_CHAT_ID):
        log.warning("Telegram не настроен (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID) - уведомление не отправлено")
        return False
    try:
        resp = requests.post(
            f"{TELEGRAM_API_URL}/sendMessage",
            json={
                'chat_id': chat_id or TELEGRAM_CHAT_ID,
                'text': text,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True,
            },
            proxies=TELEGRAM_PROXIES,
            timeout=15,
        )
        if resp.status_code != 200:
            log.warning(f"Telegram sendMessage error {resp.status_code}: {resp.text}")
            return False
        return True
    except Exception as e:
        log.warning(f"Telegram sendMessage exception: {e}")
        return False


def _now():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def notify_success(job_name, summary=None):
    text = f"✅ <b>{job_name}</b>\nВыгрузка завершена успешно\n{_now()}"
    if summary:
        text += f"\n\n{summary}"
    send_message(text)


def notify_error(job_name, error):
    text = f"❌ <b>{job_name}</b>\nОшибка при выгрузке\n{_now()}\n\n<code>{error}</code>"
    send_message(text)
