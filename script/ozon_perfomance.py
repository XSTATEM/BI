# -- coding: utf-8 --
"""
Библиотека Озон Perfomance

Автор: Олег Шабалов
Контакты: 89179021656, @olegshabalov
"""

import datetime
import requests
import json
import logging
import time
import os
import re

import lib


SLEEP_TIME = 2
SLEEP_TIME_BIG = 40
TRY = 5
OZON_DATE_FORMAT = "%Y-%m-%d"


def get_perfomance_token(key, client_id):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    data = {
        "client_id": client_id,
        "client_secret": key,
        "grant_type": "client_credentials"
    }
    url = "https://api-performance.ozon.ru/api/client/token"
    try:
        resp = requests.post(url, headers=headers, json=data)
        res = json.loads(resp.text)['access_token']
    except Exception as e:
        logging.warning(str(e))
        try:
            logging.warning(str(resp.text))
        except:
            pass
        return None
    return res


def get_perfomance_headers(token):
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }


def requests_post(url, headers=None, data=None):
    i = 0
    resp = None
    while i < TRY:
        try:
            resp = requests.post(url, headers=headers, json=data)
            # print(resp.text)
            res_dict = json.loads(str(resp.text))
        except Exception as e:
            logging.warning(str(e) + f" - TRY {i}/{TRY}")
            time.sleep(SLEEP_TIME)
            i += 1
        else:
            if resp.ok:
                break
            logging.warning(str(resp.text) + f" - TRY {i}/{TRY}")
            time.sleep(SLEEP_TIME)
            i += 1
    return resp


def requests_get(url, headers=None, params=None, verbal=True):
    i = 0
    resp = None
    while i < TRY:
        try:
            resp = requests.get(url, headers=headers, params=params)
            # print(resp.text)
            res_dict = json.loads(str(resp.text))
        except Exception as e:
            if verbal:
                logging.warning(str(e) + f" - TRY {i}/{TRY}")
            time.sleep(SLEEP_TIME)
            i += 1
        else:
            if resp.ok:
                break
            if verbal:
                logging.warning(str(resp.text) + f" - TRY {i}/{TRY}")
            time.sleep(SLEEP_TIME)
            i += 1
    return resp


def requests_post_v2(url, headers=None, data=None, sleep_time=SLEEP_TIME):
    i = 0
    resp = None
    while i < TRY:
        try:
            resp = requests.post(url, headers=headers, json=data)
            # print(resp.text)
            res_dict = json.loads(str(resp.text))
        except Exception as e:
            logging.warning(str(e) + f" - TRY {i}/{TRY}")
            time.sleep(sleep_time)
            i += 1
        else:
            if resp.ok:
                break
            logging.warning(str(resp.text) + f" - TRY {i}/{TRY}")
            time.sleep(sleep_time)
            i += 1
    return resp


def requests_get_v3(url, headers=None, params=None, trys=TRY, sleep_time=SLEEP_TIME):
    i = 0
    resp = None
    while i < trys:
        try:
            resp = requests.get(url, headers=headers, params=params)
            assert resp.ok
            # res_dict = json.loads(str(resp.text))
        except Exception as e:
            logging.warning(str(e) + f" - TRY {i}/{trys}")
            time.sleep(sleep_time)
            i += 1
        else:
            if resp.ok:
                break
            logging.warning(str(resp.text) + f" - TRY {i}/{trys}")
            time.sleep(sleep_time)
            i += 1
    return resp


def get_perfomance_campaigns(headers):
    url = "https://api-performance.ozon.ru:443/api/client/campaign"
    try:
        resp = requests_get(url, headers=headers)
        res = json.loads(resp.text)['list']
    except:
        return []
    return res


def get_perfomance_stat_un(headers, date_from, date_to):
    """
    ГГГГ-ММ-ДД
    """
    res = []

    campaigns = get_perfomance_campaigns(headers)
    campaigns_ids = []
    for campaign in campaigns:
        campaigns_ids.append(campaign.get('id'))

    url = "https://api-performance.ozon.ru:443/api/client/statistics/daily/json"
    per_request = 100

    for j in range(0, len(campaigns_ids), per_request):
        end_index = j + per_request
        if end_index >= len(campaigns_ids):
            end_index = len(campaigns_ids)
        campaigns_ids_batch = campaigns_ids[j:end_index]

        params = {
            'dateFrom': date_from,
            'dateTo': date_to,
            'campaignIds': campaigns_ids_batch
        }
        resp = requests_get(url, headers=headers, params=params)
        if not resp or not resp.ok:
            logging.warning("get_perfomance_stat_un API error")
            continue
        try:
            res_dict = json.loads(resp.text)
            res_batch = res_dict['rows']
        except Exception as e:
            logging.warning(f"get_perfomance_stat_un API error - {str(e)}")
            continue
        res.extend(res_batch)

    return res


def get_campaign_skus(headers, date_from, date_to):
    """
    ГГГГ-ММ-ДД
    """
    res = []

    campaigns = get_perfomance_campaigns(headers)
    # campaign/{id}/objects существует только у SKU-кампаний (товарное продвижение).
    # У BANNER и прочих типов кампаний объектов нет - запрос всегда падает с ошибкой,
    # но требует TRY*SLEEP_TIME секунд на каждую попытку, что при сотнях таких кампаний
    # превращает выгрузку в часы бессмысленных запросов - поэтому отсекаем их заранее.
    skipped = len(campaigns)
    campaigns = [c for c in campaigns if c.get('advObjectType') == 'SKU']
    skipped -= len(campaigns)
    if skipped:
        logging.info(f"get_campaign_skus - пропускаем {skipped} не-SKU кампаний (нет /objects)")

    for campaign in campaigns:
        campaign_id = campaign.get('id')
        if not campaign_id:
            continue
        url = f"https://api-performance.ozon.ru:443/api/client/campaign/{campaign_id}/objects"
        resp = requests_get(url, headers=headers, verbal=False)
        if not resp or not resp.ok:
            logging.warning(f"campaign/{campaign_id}/objects API error")
            continue
        try:
            res_dict = json.loads(resp.text)
            raw_res = res_dict['list']
        except Exception as e:
            logging.warning(f"get_perfomance_stat_un API error - {str(e)}")
            continue
        for elem in raw_res:
            res.append(
                {
                    'campaign_id': campaign_id,
                    'sku': elem.get('id')
                }
            )

    return res


def download_report(headers, report_id, file_name):
    url = 'https://api-performance.ozon.ru:443/api/client/statistics/report'
    params = {
        'UUID': report_id,
    }
    resp = requests_get_v3(url, headers=headers, params=params, sleep_time=SLEEP_TIME_BIG)
    # logging.info(resp.text)
    # print(str(resp.text).encode('cp1251', 'ignore').decode('utf8'))
    # print(str(resp.text).encode('cp1251', 'ignore').decode('cp1251'))
    if not resp or not resp.ok:
        logging.info(f"download_report API error - {resp.text}")
        return False
    try:
        with open(file_name, 'wb') as f:
            f.write(resp.content)
        return True
    except Exception as e:
        logging.info(f"download_report API error - {str(e)}")
        return False


def clear_norm_rus_header(text):
    text = re.sub(r"\([^()]*\)", "", text).strip()
    text = re.sub(r"[^\w\s]", "", text)
    text = text.strip().replace(' ', '_')
    text = re.sub(r'_+', '_', text).strip('_')
    text = text.lower()
    # Ограничиваем до 63 байт (лимит PostgreSQL)
    encoded = text.encode('utf-8')
    if len(encoded) > 63:
        text = encoded[:62].decode('utf-8', errors='ignore').rstrip('_')
    return text                                      # lowercase для PostgreSQL

def read_csv_ozon_product_advert(file_path):
    delimiter = ';'
    encoding = 'utf8'
    res = []
    header_dict = {}
    try:
        with open(file_path, 'r', encoding=encoding, errors='ignore') as f:
            # ── ОТЛАДКА: показываем первые 3 строки файла ──
            preview = [next(f, '') for _ in range(3)]
            logging.info(f"Превью {os.path.basename(file_path)}: {preview}")
            f.seek(0)  # возвращаемся в начало
            # ───────────────────────────────────────────────
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue

                # Ищем строку с заголовками: содержит текстовые значения, не цифры
                if not header_dict:
                    cells = line.split(delimiter)
                    # Заголовок — если больше половины ячеек непустые строки (не числа)
                    text_cells = [c for c in cells if c.strip() and not c.strip().replace('.','').replace('-','').replace(',','').isdigit()]
                    if len(text_cells) >= 3:
                        header_dict = {
                            index: clear_norm_rus_header(key)
                            for index, key in enumerate(cells)
                        }
                    continue  # в любом случае строку с заголовком в данные не пишем

                elif not line.startswith('Всего') and not line.startswith('Корректировка'):
                    res_elem = {
                        header_dict.get(index): elem
                        for index, elem in enumerate(line.split(delimiter))
                        if header_dict.get(index)
                    }
                    res.append(res_elem)
    except Exception as e:
        logging.warning(str(e))
    return res


def get_perfomance_full_stat_un(headers, date_from, date_to):
    """
    ГГГГ-ММ-ДД
    get_perfomance_full_stat_un(ozon_perfomance_headers, "2025-10-14", "2025-10-14")
    """
    temp_dir = os.path.join(os.getcwd(), 'temp/')
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    res = []

    campaigns = get_perfomance_campaigns(headers)
    campaigns_ids = [c.get('id') for c in campaigns]
    logging.info(f"Всего кампаний: {len(campaigns_ids)}, период: {date_from} → {date_to}")

    # ── ТЕСТ: убрать срез когда всё проверено ──────────────────────────
    campaigns_ids = campaigns_ids[:10]
    logging.info(f"Тестовый режим: берём первые {len(campaigns_ids)} кампаний")
    # ───────────────────────────────────────────────────────────────────

    dt_since_obj = datetime.datetime.strptime(date_from, OZON_DATE_FORMAT)
    dt_to_obj    = datetime.datetime.strptime(date_to,   OZON_DATE_FORMAT)
    dt_cur_obj   = dt_since_obj

    while dt_cur_obj <= dt_to_obj:
        dt_cur_str = dt_cur_obj.strftime(OZON_DATE_FORMAT)
        logging.info(f"── Дата: {dt_cur_str} ──")

        per_request = 10
        url = "https://api-performance.ozon.ru:443/api/client/statistics"

        for j in range(0, len(campaigns_ids), per_request):
            end_index = min(j + per_request, len(campaigns_ids))
            campaigns_ids_batch = campaigns_ids[j:end_index]
            logging.info(f"  Батч {j}–{end_index}: запрашиваю UUID...")

            params = {
                'dateFrom':  dt_cur_str,
                'dateTo':    dt_cur_str,
                'campaigns': campaigns_ids_batch,
                'groupBy':   'DATE',
            }
            resp = requests_post_v2(url, headers=headers, data=params, sleep_time=SLEEP_TIME_BIG)

            try:
                res_dict = json.loads(resp.text)
                if 'error' in res_dict:
                    err_msg = str(res_dict.get('error', ''))
                    logging.warning(f"  Ошибка API: {err_msg}")
                    if 'авторизац' in err_msg.lower() or 'unauthorized' in err_msg.lower():
                        logging.warning("  Токен протух — останавливаемся")
                        return res
                    continue
                UUID = res_dict['UUID']
                logging.info(f"  UUID получен: {UUID}, жду {SLEEP_TIME_BIG} сек...")
            except Exception as e:
                logging.warning(f"  Ошибка получения UUID: {str(e)}, ответ: {resp.text[:200] if resp else 'нет ответа'}")
                continue

            time.sleep(SLEEP_TIME_BIG)

            zip_filepath = os.path.join(temp_dir, f"{UUID}.zip")
            if download_report(headers, UUID, zip_filepath):
                logging.info(f"  Файл скачан: {zip_filepath}")
                unzip_dir = os.path.join(temp_dir, f"{UUID}/")
                if not os.path.exists(unzip_dir):
                    os.makedirs(unzip_dir)
                if lib.unzip_files(zip_filepath, unzip_dir):
                    for dirpath, dirname, filenames in os.walk(unzip_dir):
                        for filename in filenames:
                            name, ext = os.path.splitext(filename)
                            try:
                                campaign_id, dates = name.split('_')
                                date, date1 = dates.split('-')
                                assert date == date1
                            except Exception as e:
                                logging.warning(f"  Не удалось разобрать имя файла {filename}: {str(e)}")
                                continue

                            rows = read_csv_ozon_product_advert(os.path.join(dirpath, filename))
                            if rows:
                                logging.info(f"  {filename}: {len(rows)} строк, колонки: {list(rows[0].keys())[:6]}")
                            else:
                                logging.warning(f"  {filename}: пустой файл или не распарсился")
                                continue

                            for row in rows:
                                row['date']        = date
                                row['campaign_id'] = campaign_id
                                if not row.get('sku'):
                                    row['sku'] = row.get('Артикул') or '0'
                                row['order_id'] = row.get('Номер_заказа', '0')
                            res.extend(rows)
                else:
                    logging.warning(f"  Не удалось распаковать {zip_filepath}")
            else:
                logging.warning(f"  Не удалось скачать файл для UUID {UUID}")

        dt_cur_obj += datetime.timedelta(days=1)

    logging.info(f"Итого строк собрано: {len(res)}")
    return res


def get_perfomance_full_stat_un_temp(headers, date_from, date_to):
    """
    ГГГГ-ММ-ДД
    get_perfomance_full_stat_un(ozon_perfomance_headers, "2025-10-14", "2025-10-14")
    """
    temp_dir = os.path.join(os.getcwd(), 'temp/')
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    res = []

    for dirpath, dirname, filenames in os.walk(temp_dir):
        for filename in filenames:
            name, ext = os.path.splitext(filename)
            if 'csv' not in ext:
                continue
            try:
                campaign_id, dates = name.split('_')
                date, date1 = dates.split('-')
                assert date == date1
            except Exception as e:
                logging.warning(f'Split filename {filename} error - {str(e)}')
                continue
            rows = read_csv_ozon_product_advert(os.path.join(dirpath, filename))
            for row in rows:
                row['date'] = date
                row['campaign_id'] = campaign_id
                if not row.get('sku'): #Я думаю лучше разделить кампании
                    row['sku'] = row.get('Артикул')
                    if not row['sku']:
                        row['sku'] = '0'
                row['order_id'] = row.get('Номер_заказа', '0')
            res.extend(rows)

    return res
