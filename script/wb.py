# -- coding: utf-8 --
"""
WB lib
"""
import sys
from typing import List, Union, Dict
import logging
import requests
import datetime
import time
import uuid
import os
from pathlib import Path

import lib
from settings import WB_PAGINATION_LIMIT, TRY, SLEEP_TIME, SLEEP_TIME_REPORT, WB_DATE_FORMAT, WB_DATETIME_FORMAT, \
    SLEEP_TIME_ANALYTICS, DIR_DATA

DEBUG_MODE = False


def requests_get(url, headers, params=None, sleep_time=SLEEP_TIME):
    i = 0
    resp = None
    while i < TRY:
        try:
            resp = requests.get(url, headers=headers, params=params)
            
            if resp.status_code == 429:
                # Пытаемся достать точное время бана в секундах, если его нет - берем дефолтное
                reset_time = int(resp.headers.get('x-ratelimit-reset', sleep_time))
                logging.warning(f"Поймали 429 бан. Ждем {reset_time} секунд.")
                time.sleep(reset_time + 1) # +1 секунда сверху для надежности
                i += 1
                continue
                
            res = resp.json()
        except Exception as e:
            logging.warning(str(e))
            time.sleep(sleep_time)
            i += 1
            continue
            
        if not resp.ok or not res: 
            time.sleep(sleep_time)
            i += 1
            continue
        break

    return resp


def requests_get_v2(url, headers, params=None, sleep_time=SLEEP_TIME, trys=TRY):
    i = 0
    resp = None
    while i < trys:
        try:
            resp = requests.get(url, headers=headers, params=params)
            
            if resp.status_code == 429:
                # Берем точное время блокировки из заголовка. Если его нет - используем дефолтное.
                reset_time = int(resp.headers.get('x-ratelimit-reset', sleep_time))
                logging.warning(f"Блок 429. Ожидание снятия лимита: {reset_time} сек.")
                time.sleep(reset_time + 1) 
                i += 1
                continue
            
            print(resp.text) # Закомментируй или удали, чтобы не засорять вывод, когда всё заработает
            res = resp.json()
            
        except Exception as e:
            logging.warning(str(e))
            time.sleep(sleep_time)
            i += 1
            continue
            
        if not resp.ok or not res: #FIXME 23/08 or not res
            time.sleep(sleep_time)
            i += 1
            continue
        break

    return resp


def requests_post(url, headers, data=None, sleep_time=SLEEP_TIME, error_exception=None):
    i = 0
    resp = None
    while i < TRY:
        try:
            resp = requests.post(url, headers=headers, json=data)
            print(resp.text)
            res = resp.json()
        except Exception as e:
            logging.warning(str(e))
            try:
                logging.warning(str(resp.text).replace('\n', ''))
            except:
                pass
            time.sleep(sleep_time)
            i += 1
            continue
        if not resp.ok:
            if error_exception and 'error' in res and res['error'] == error_exception:
                break
            logging.warning(str(resp.text).replace('\n', '') + f"(URL {url}, body: {data} TRY {i+1}/{TRY})")
            time.sleep(sleep_time)
            i += 1
            continue
        break

    return resp


def get_header(token: str) -> Dict:
    header = {
        "Authorization": token,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    return header


def get_orders_un(token, dt_since_str, dt_to_str) -> List:
    url = f"https://statistics-api.wildberries.ru/api/v1/supplier/orders?dateFrom={dt_since_str}"
    header = get_header(token)
    res = []

    resp = requests_get(url, headers=header)
    if not resp or not resp.ok:
        logging.warning('WB API error')
        try:
            logging.warning(resp.text)
        except Exception as e:
            logging.warning(str(e))
        return res
    try:
        res = resp.json()
    except Exception as e:
        logging.warning(str(e))

    return res


def get_orders_un_v2(token, dt_since_str, dt_to_str) -> List:
    url = f"https://statistics-api.wildberries.ru/api/v1/supplier/orders?dateFrom={dt_since_str}"
    header = get_header(token)
    res = []

    resp = requests_get_v2(url, headers=header, sleep_time=5, trys=7)
    if not resp or not resp.ok:
        logging.warning('WB API error')
        try:
            logging.warning(resp.text)
        except Exception as e:
            logging.warning(str(e))
        return res
    try:
        res = resp.json()
    except Exception as e:
        logging.warning(str(e))

    return res


def get_sales_un(token, dt_since_str, dt_to_str) -> List:
    url = f"https://statistics-api.wildberries.ru/api/v1/supplier/sales?dateFrom={dt_since_str}"
    header = get_header(token)
    res = []

    resp = requests_get(url, headers=header)
    if not resp or not resp.ok:
        logging.warning('WB API error')
        try:
            logging.warning(resp.text)
        except Exception as e:
            logging.warning(str(e))
        return res
    try:
        res = resp.json()
    except Exception as e:
        logging.warning(str(e))

    return res


def get_incomes_un(token, dt_since_str, dt_to_str) -> List:
    url = f"https://statistics-api.wildberries.ru/api/v1/supplier/incomes?dateFrom={dt_since_str}"
    header = get_header(token)
    res = []

    resp = requests_get(url, headers=header)
    if not resp or not resp.ok:
        logging.warning('WB API error')
        try:
            logging.warning(resp.text)
        except Exception as e:
            logging.warning(str(e))
        return res
    try:
        res = resp.json()
    except Exception as e:
        logging.warning(str(e))

    return res


# GET /api/v5/supplier/reportDetailByPeriod отключён WB 15 июля - заменён на
# POST /api/finance/v1/sales-reports/detailed (finance-api.wildberries.ru).
# Новый метод отдаёт поля в camelCase и часть из них переименована относительно
# старого API (см. таблицу сопоставления в changelog WB) - WB_REPORT_FIELD_RENAME_MAP
# переименовывает их обратно в старые snake_case имена, чтобы структура таблиц
# wb_report_rrd/wb_report_rrd_day не менялась для уже существующих полей.
# suppliercontract_code и ppvz_supplier_id в новом методе не отдаются - соответствующие
# колонки перестанут обновляться, но не удаляются. Полностью новые поля
# (title, b2bCustomerTin, paidWithSocialCertificate) переименования не требуют -
# они лягут в новые колонки таблицы через штатный механизм add_table_column.
WB_REPORT_FIELD_RENAME_MAP = {
    'reportId': 'realizationreport_id',
    'rrdId': 'rrd_id',
    'createDate': 'create_dt',
    'currency': 'currency_name',
    'vendorCode': 'sa_name',
    'techSize': 'ts_name',
    'sku': 'barcode',
    'sellerOperName': 'supplier_oper_name',
    'rrDate': 'rr_dt',
    'retailPriceWithDisc': 'retail_price_withdisc_rub',
    'deliveryService': 'delivery_rub',
    'sellerPromo': 'supplier_promo',
    'spp': 'ppvz_spp_prc',
    'kvwBase': 'ppvz_kvw_prc_base',
    'kvw': 'ppvz_kvw_prc',
    'supRatingUp': 'sup_rating_prc_up',
    'forPay': 'ppvz_for_pay',
    'vw': 'ppvz_vw',
    'vwNds': 'ppvz_vw_nds',
    'ppvzSupplierInn': 'ppvz_inn',
    'country': 'site_country',
    'paidStorage': 'storage_fee',
    'paidAcceptance': 'acceptance',
    'orderId': 'assembly_id',
    'isB2b': 'is_legal_entity',
    'wibesDiscountPercent': 'wibes_wb_discount_percent',
}

WB_FINANCE_REPORT_URL = "https://finance-api.wildberries.ru/api/finance/v1/sales-reports/detailed"


def _rename_report_item_fields(item: Dict) -> Dict:
    return {WB_REPORT_FIELD_RENAME_MAP.get(key, key): value for key, value in item.items()}


def _requests_post_report_page(url, headers, data, sleep_time=SLEEP_TIME_REPORT):
    i = 0
    resp = None
    while i < TRY:
        try:
            resp = requests.post(url, headers=headers, json=data)
        except Exception as e:
            logging.warning(str(e))
            time.sleep(sleep_time)
            i += 1
            continue

        if resp.status_code == 429:
            reset_time = int(resp.headers.get('x-ratelimit-reset', sleep_time))
            logging.warning(f"Поймали 429 бан. Ждем {reset_time} секунд.")
            time.sleep(reset_time + 1)
            i += 1
            continue

        if resp.status_code == 204 or resp.ok:
            return resp

        logging.warning(str(resp.text))
        time.sleep(sleep_time)
        i += 1

    return resp


def _get_report_paginated(token, dt_since_str, dt_to_str, period=None) -> List:
    header = get_header(token)
    res = []

    rrdid = 0
    while True:
        data = {
            'dateFrom': dt_since_str,
            'dateTo': dt_to_str,
            'rrdId': rrdid,
        }
        if period:
            data['period'] = period

        resp = _requests_post_report_page(WB_FINANCE_REPORT_URL, headers=header, data=data, sleep_time=SLEEP_TIME_REPORT)
        if not resp:
            logging.warning(f"No response from {WB_FINANCE_REPORT_URL}")
            break
        if resp.status_code == 204:
            logging.info(f"Empty result (204) from - {WB_FINANCE_REPORT_URL}")
            break
        if not resp.ok:
            logging.warning(str(resp.text))
            break

        try:
            res_list = resp.json()
        except Exception as e:
            logging.warning(str(e))
            break

        if not res_list:
            logging.info(f"Empty result from - {WB_FINANCE_REPORT_URL}")
            break
        rrdid_new = res_list[-1]['rrdId']
        if not rrdid_new:
            logging.info(f"Empty rrdId in {res_list[-1]}")
            break

        if rrdid_new == rrdid:
            logging.warning('Repeat last rrdid')
            break

        res.extend(_rename_report_item_fields(item) for item in res_list)
        rrdid = rrdid_new
        time.sleep(SLEEP_TIME_REPORT)  # лимит WB на sales-reports/detailed ~1 запрос/мин - пауза между страницами обязательна

    return res


def get_report(token, dt_since_str, dt_to_str) -> List:
    return _get_report_paginated(token, dt_since_str, dt_to_str)


def get_report_un(token, dt_since_str, dt_to_str):
    WB_REPORT_PERIOD_DAYS = 7 #FIXME 7

    dt_since_obj = datetime.datetime.strptime(dt_since_str, WB_DATETIME_FORMAT)
    dt_to_obj = datetime.datetime.strptime(dt_to_str, WB_DATETIME_FORMAT)

    elems = []
    dt_cur_obj = dt_since_obj
    while dt_cur_obj < dt_to_obj:
        dt_cur_obj += datetime.timedelta(days=WB_REPORT_PERIOD_DAYS)
        dt_to_str = dt_cur_obj.strftime(WB_DATETIME_FORMAT)
        elems.extend(get_report(token, dt_since_str, dt_to_str))
        dt_since_str = dt_cur_obj.strftime(WB_DATETIME_FORMAT)

    return elems


def get_report_day_un(token, dt_since_str, dt_to_str) -> List:
    return _get_report_paginated(token, dt_since_str, dt_to_str, period='daily')


def get_stocks_un(token, dt_since_str=None, dt_to_str=None) -> List:
    """
    Метод GET /api/v1/supplier/stocks отключён WB 23 июня - стал стабильно
    отдавать пустой ответ (см. log_main.txt, wb_daily_stocks/wb_stocks2 с 07-16/07-21).
    Заменён на актуальный метод "Остатки на складах WB" (Аналитика):
    POST /api/analytics/v1/stocks-report/wb-warehouses.
    ВАЖНО: новый метод отдаёт остатки в разрезе nmId/chrtId/склад и НЕ содержит
    supplierArticle/barcode - см. main.py, index_fields для wb_stocks2/
    wb_daily_stocks обновлены на ['nmId', 'chrtId', 'warehouseId'].
    Лимит WB: 3 запроса/мин (~1 запрос/20 сек) - используем SLEEP_TIME_ANALYTICS.
    """
    url = "https://seller-analytics-api.wildberries.ru/api/analytics/v1/stocks-report/wb-warehouses"
    header = get_header(token)
    res = []
    limit = 250000
    offset = 0

    while True:
        data = {
            'limit': limit,
            'offset': offset,
        }
        resp = requests_post(url, headers=header, data=data, sleep_time=SLEEP_TIME_ANALYTICS)
        if not resp or not resp.ok:
            logging.warning('WB API error - get_stocks_un (stocks-report/wb-warehouses)')
            try:
                logging.warning(resp.text)
            except Exception as e:
                logging.warning(str(e))
            break
        try:
            items = resp.json()['data']['items']
        except Exception as e:
            logging.warning(str(e))
            break

        res.extend(items)
        if len(items) < limit:
            break
        offset += limit
        time.sleep(SLEEP_TIME_ANALYTICS)

    return res


def get_report_status(token, task_id):
    """
    :param start_day: %Y-%m-%d
    """
    header = get_header(token)
    url = f"https://seller-analytics-api.wildberries.ru/api/v1/paid_storage/tasks/{task_id}/status"

    resp = requests_get(url, headers=header)
    if not resp or not resp.ok:
        logging.warning(str(resp.text))
        return False
    try:
        status = resp.json()['data']['status']
    except Exception as e:
        logging.warning(str(e))
        return False

    return status == 'done'


def get_report_done(token, task_id):
    """
    :param start_day: %Y-%m-%d
    """
    header = get_header(token)
    url = f"https://seller-analytics-api.wildberries.ru/api/v1/paid_storage/tasks/{task_id}/download"
    res = []

    resp = requests_get(url, headers=header)
    if not resp or not resp.ok:
        logging.warning(str(resp.text))
        return res

    try:
        res = resp.json()
    except Exception as e:
        logging.warning(str(e))

    return res


def get_storage_report_un(token, dt_since_str, dt_to_str) -> List:
    """
    :param start_day: %Y-%m-%d
    """
    header = get_header(token)
    res = []

    url = f"https://seller-analytics-api.wildberries.ru/api/v1/paid_storage?dateFrom={dt_since_str}&dateTo={dt_to_str}"

    resp = requests_get(url, headers=header)
    if not resp or not resp.ok:
        logging.warning(str(resp.text) if resp else "No response (request failed)")
        return res
    print(resp.text)

    task_id = None
    try:
        task_id = resp.json()['data']['taskId']
    except Exception as e:
        logging.warning(str(e))
        return res

    limit = 100
    i = 0
    while not get_report_status(token, task_id):
        time.sleep(10)
        i += 1
        if i >= limit:
            logging.warning(f"Over limit get_storage_report_un - stop")
            break

    return get_report_done(token, task_id)


def get_upd(token, dt_since_str, dt_to_str) -> List:
    url = f"https://advert-api.wildberries.ru/adv/v1/upd?from={dt_since_str}&to={dt_to_str}"
    header = get_header(token)
    res = []

    resp = requests_get(url, headers=header)
    if resp:
        print(resp.text)
    if not resp or not resp.ok:
        logging.warning('WB API error - get_upd')
        try:
            logging.warning(resp.text)
        except Exception as e:
            logging.warning(str(e))
        return res
    try:
        res = resp.json()
    except Exception as e:
        logging.warning(str(e))

    return res



def get_all_adverts(token, dt_since_obj: datetime.datetime) -> List:
    """statuses
        string
        Example: statuses=-1,4,8
        Статусы кампаний:

        -1 — удалена, процесс удаления будет завершён в течение 10 минут
        4 — готова к запуску
        7 — завершена
        8 — отменена
        9 — активна
        11 — на паузе
    """
    raw_res = []
    url = f"https://advert-api.wildberries.ru/api/advert/v2/adverts?statuses=9,11,7"
    header = get_header(token)

    resp = requests_get(url, headers=header)
    if resp:
        print(resp.text)
    if not resp or not resp.ok:
        logging.warning('WB API error - get_all_adverts')
        try:
            logging.warning(resp.text)
        except Exception as e:
            logging.warning(str(e))
        return raw_res
    try:
        raw_res = resp.json()['adverts']
    except Exception as e:
        logging.warning(str(e))

    res = []
    for adv in raw_res:
        try:
            upd_obj = datetime.datetime.strptime(adv.get('timestamps', {}).get('updated', '').split('T')[0], "%Y-%m-%d")
        except Exception as e:
            logging.warning(f"get_all_adverts upd_obj error - {str(e)}")
            continue

        if upd_obj >= dt_since_obj:
            res.append(adv)

    return res


def get_adverts_info(token, adverts):
    header = get_header(token)
    WB_ADVERT_ID_LIMIT = 50
    res = []

    for j in range(0, len(adverts), WB_ADVERT_ID_LIMIT):
        end_adverts_index = j + WB_ADVERT_ID_LIMIT
        if end_adverts_index >= len(adverts):
            end_adverts_index = len(adverts)
        adverts_batch = adverts[j:end_adverts_index]

        url = f"https://advert-api.wildberries.ru/adv/v1/promotion/adverts"
        data = adverts_batch
        resp = requests.post(url, headers=header, json=data)
        if not resp or not resp.ok:
            logging.warning('WB API error - get_adverts_info')
            try:
                logging.warning(resp.text)
            except Exception as e:
                logging.warning(str(e))
            continue
        try:
            res_batch = resp.json()
        except Exception as e:
            logging.warning(str(e))
        else:
            res.extend(res_batch)

    return res


def get_adverts_un(token, dt_since_str, dt_to_str):
    upds = get_upd(token, dt_since_str, dt_to_str)
    adverts_set = set()
    for upd in upds:
        adverts_set.add(upd.get('advertId'))
    raw_adverts = get_adverts_info(token, list(adverts_set))
    adverts_dict = dict()
    for elem in raw_adverts:
        adverts_dict[elem.get('advertId')] = elem
    for upd in upds:
        upd['adv'] = adverts_dict.get(upd.get('advertId'))
        # if not upd.get('updTime'): #FIXME 28/08
        #     upd['updTime'] = upd['adv'].get('createTime')
    return upds


def get_adverts_stat(token, adverts_ids, dates) -> List:
    header = get_header(token)
    res = []

    url = f"https://advert-api.wildberries.ru/adv/v2/fullstats"
    # logging.info(url)
    data = []
    for adv_id in adverts_ids:
        data.append(
            {
                'id': adv_id,
                'dates': dates
            }
        )

    resp = requests_post(url, headers=header, data=data, sleep_time=SLEEP_TIME_REPORT, error_exception='некорректные параметры запроса: нет кампаний с корректными интервалами')
    print(resp.text)
    if not resp or not resp.ok:
        logging.warning(f"get_adverts_stat - {url} error request")
        logging.warning(resp.text)
        return res

    try:
        res = resp.json()
    except Exception as e:
        logging.warning(str(e))

    return res


def get_adverts_stat_v2(token, adverts_ids, dt_since_str, dt_to_str) -> List:
    header = get_header(token)
    res = []

    url = f"https://advert-api.wildberries.ru/adv/v3/fullstats"
    params = {
        'ids': ','.join(list(map(str, adverts_ids))),
        'beginDate': dt_since_str,
        'endDate': dt_to_str,
    }

    resp = requests_get(url, headers=header, params=params, sleep_time=SLEEP_TIME_ANALYTICS)
    print(resp.text)
    if not resp or not resp.ok:
        logging.warning(f"get_adverts_stat_v2 - {url} error request")
        if resp:
            logging.warning(resp.text)
        return res

    try:
        res = resp.json()
    except Exception as e:
        logging.warning(str(e))

    return res


def get_adverts_stat_un(token, dt_since_str, dt_to_str):
    WB_ADVERT_PERIOD_DAYS = 10
    WB_ADVERT_ID_LIMIT = 50 #FIXME 100

    upds = get_upd(token, dt_since_str, dt_to_str)
    adverts_set = set()
    for upd in upds:
        adverts_set.add(upd.get('advertId'))
    adverts = list(adverts_set)
    # print(adverts)

    dates = []
    dt_since_obj = datetime.datetime.strptime(dt_since_str, WB_DATE_FORMAT)
    dt_to_obj = datetime.datetime.strptime(dt_to_str, WB_DATE_FORMAT)
    dt_cur_obj = dt_since_obj
    while dt_cur_obj <= dt_to_obj:
        dates.append(dt_cur_obj.strftime(WB_DATE_FORMAT))
        dt_cur_obj += datetime.timedelta(days=1)

    adverts_stat = []
    for i in range(0, len(dates), WB_ADVERT_PERIOD_DAYS):
        end_index = i + WB_ADVERT_PERIOD_DAYS
        if end_index >= len(dates):
            end_index = len(dates)
        dates_batch = dates[i:end_index]

        for j in range(0, len(adverts), WB_ADVERT_ID_LIMIT):
            end_adverts_index = j + WB_ADVERT_ID_LIMIT
            if end_adverts_index >= len(adverts):
                end_adverts_index = len(adverts)
            adverts_batch = adverts[j:end_adverts_index]

            raw_adverts_stat = get_adverts_stat(token, adverts_batch, dates_batch)
            if raw_adverts_stat:
                logging.info(
                    f"Recieved {len(raw_adverts_stat)} stats for {len(adverts_batch)} adverts and {dates_batch} dates")
                for raw_advert in raw_adverts_stat:
                    for elem in raw_advert.get('days', []):
                        elem['advertId'] = raw_advert['advertId']
                        adverts_stat.append(elem)
                time.sleep(SLEEP_TIME_REPORT)

    return adverts_stat


def get_adverts_stat_un_v2(token, dt_since_str, dt_to_str):
    WB_ADVERT_PERIOD_DAYS = 2
    WB_ADVERT_ID_LIMIT = 50 #FIXME 100

    upds = get_upd(token, dt_since_str, dt_to_str)
    adverts_set = set()
    for upd in upds:
        adverts_set.add(upd.get('advertId'))
    adverts = list(adverts_set)
    # print(adverts)

    adverts_stat = []
    for j in range(0, len(adverts), WB_ADVERT_ID_LIMIT):
        end_adverts_index = j + WB_ADVERT_ID_LIMIT
        if end_adverts_index >= len(adverts):
            end_adverts_index = len(adverts)
        adverts_batch = adverts[j:end_adverts_index]

        raw_adverts_stat = get_adverts_stat_v2(token, adverts_batch, dt_since_str, dt_to_str)
        if raw_adverts_stat:
            logging.info(
                f"Recieved {len(raw_adverts_stat)} stats for {len(adverts_batch)} adverts and {dt_since_str}-{dt_to_str} dates")
            for raw_advert in raw_adverts_stat:
                for elem in raw_advert.get('days', []):
                    elem['advertId'] = raw_advert['advertId']
                    adverts_stat.append(elem)
            time.sleep(SLEEP_TIME_REPORT)

    return adverts_stat


def get_adverts_stat_un_v3(token, dt_since_str, dt_to_str):
    WB_ADVERT_PERIOD_DAYS = 2
    WB_ADVERT_ID_LIMIT = 50 #FIXME 50
    adverts_set = set()

    #### Get IDs - var1
    upds = get_upd(token, dt_since_str, dt_to_str)
    for upd in upds:
        adverts_set.add(upd.get('advertId'))
    ####

    #### Get IDs - var2
    # try:
    #     dt_since_obj = datetime.datetime.strptime(dt_since_str, "%Y-%m-%d")
    # except Exception as e:
    #     logging.warning(f"get_adverts_stat_un_v3 - {str(e)}")
    #     return []
    #
    # upds = get_all_adverts(token, dt_since_obj)
    # for upd in upds:
    #     adverts_set.add(upd.get('id'))
    ####

    adverts = list(adverts_set)
    logging.info(f"recieved {len(adverts)} adverts ids for get_adverts_stat_un_v3")

    adverts_stat = []
    for j in range(0, len(adverts), WB_ADVERT_ID_LIMIT):
        end_adverts_index = j + WB_ADVERT_ID_LIMIT
        if end_adverts_index >= len(adverts):
            end_adverts_index = len(adverts)
        adverts_batch = adverts[j:end_adverts_index]

        raw_adverts_stat = get_adverts_stat_v2(token, adverts_batch, dt_since_str, dt_to_str)
        # print(raw_adverts_stat, adverts_batch)
        if raw_adverts_stat:
            logging.info(
                f"Recieved {len(raw_adverts_stat)} stats for {len(adverts_batch)} adverts and {dt_since_str}-{dt_to_str} dates")
            for raw_advert in raw_adverts_stat:
                for day_elem in raw_advert.get('days', []):
                    for app_elem in day_elem.get('apps', []):
                        for nm_elem in app_elem.get('nms', []):
                            nm_elem['advertId'] = raw_advert['advertId']
                            for key in app_elem:
                                if key not in nm_elem and key != 'nms':
                                    nm_elem[key] = app_elem[key]
                            for key in day_elem:
                                if key not in nm_elem and key != 'apps':
                                    nm_elem[key] = day_elem[key]
                            nm_elem['appType'] = str(nm_elem.get('appType', 0))
                            adverts_stat.append(nm_elem)
            time.sleep(SLEEP_TIME_REPORT)

    return adverts_stat

# ============================================================

def get_normquery_stats(token, items, dt_since_str, dt_to_str) -> List:
    """
    items: список словарей [{"advert_id": 123, "nm_id": 456}, ...]  (максимум 100 за раз)
    Возвращает СЫРОЙ ответ WB (список по advert_id/nm_id с вложенной статистикой по фразам).
    """
    header = get_header(token)
    res = []

    url = f"https://advert-api.wildberries.ru/adv/v1/normquery/stats"
    data = {
        "from": dt_since_str,
        "to": dt_to_str,
        "items": items,
    }

    # лимит метода: 10 запросов / 1 мин, интервал 6 сек — берём с запасом
    resp = requests_post(url, headers=header, data=data, sleep_time=7)
    if not resp or not resp.ok:
        logging.warning(f"get_normquery_stats - {url} error request")
        if resp:
            logging.warning(resp.text)
        return res

    try:
        res = resp.json().get('stats', [])
    except Exception as e:
        logging.warning(str(e))

    return res


def get_advert_nm_pairs(token, dt_since_str, dt_to_str) -> List[Dict]:
    """
    Достаёт уникальные пары (advert_id, nm_id), переиспользуя уже работающий
    get_adverts_stat_un_v3 (там nm_id уже прилетает в каждой строке как nmId).
    """
    raw_stat = get_adverts_stat_un_v3(token, dt_since_str, dt_to_str)
    pairs_set = set()
    for row in raw_stat:
        advert_id = row.get('advertId')
        nm_id = row.get('nmId')
        if advert_id and nm_id:
            pairs_set.add((advert_id, nm_id))
    return [{"advert_id": a, "nm_id": n} for a, n in pairs_set]


def get_normquery_stats_un(token, dt_since_str, dt_to_str) -> List:
    """
    Оркестратор: берёт все пары advert_id+nm_id за период, бьёт на пачки по 100,
    дёргает get_normquery_stats с уважением к лимиту 10 запросов/мин (интервал 6 сек),
    разворачивает в плоский список строк.
    """
    NORMQUERY_ITEMS_LIMIT = 100

    pairs = get_advert_nm_pairs(token, dt_since_str, dt_to_str)
    logging.info(f"get_normquery_stats_un - {len(pairs)} advert/nm pairs")

    result = []
    for i in range(0, len(pairs), NORMQUERY_ITEMS_LIMIT):
        batch = pairs[i:i + NORMQUERY_ITEMS_LIMIT]
        raw = get_normquery_stats(token, batch, dt_since_str, dt_to_str)

        for advert_block in raw:
            advert_id = advert_block.get('advert_id')
            nm_id = advert_block.get('nm_id')
            for stat_elem in advert_block.get('stats', []):
                stat_elem['advert_id'] = advert_id
                stat_elem['nm_id'] = nm_id
                result.append(stat_elem)

        time.sleep(7)  # лимит метода: 10 запросов/мин

    return result


##################################################### DONT USE #########################################################

def get_categories(token):
    header = get_header(token)
    url = "https://suppliers-api.wildberries.ru/api/v1/directory/tech-sizes?top=10000"
    # url = 'https://suppliers-api.wildberries.ru/api/v1/config/get/object/all?top=10000'
    resp = requests.get(url, headers=header)
    if not resp.ok:
        return None
    print(resp.text)


def get_warehouses(token):
    header = get_header(token)
    url = "https://suppliers-api.wildberries.ru/api/v2/warehouses"
    resp = requests.get(url, headers=header)
    if not resp.ok:
        return None
    print(resp.text)


def get_cards(token):
    header = get_header(token)
    url = f"https://suppliers-api.wildberries.ru/card/list"
    data = {
        "id": "1",
        "jsonrpc": "2.0",
        "params": {
            "filter": {
                "find": [
                    {
                        "column": "nomenclatures.variations.barcode",
                        "search": ''
                    }
                ]
            },
            "query": {
                "limit": 10,
                "offset": 0
            }
        }
    }
    resp = requests.post(url, headers=header, json=data)
    try:
        cards = resp.json()["result"]["cards"]
    except:
        return {}
    else:
        return cards


def get_stock_dicts(token):
    """
    nmId is Key, barcode is Value
    """
    header = get_header(token)
    skip = 0
    take = WB_PAGINATION_LIMIT
    total = skip + 1
    res_art_key = {}
    res_bar_key = {}
    while skip < total:
        url = f"https://suppliers-api.wildberries.ru/api/v2/stocks?skip={skip}&take={take}"
        resp = requests.get(url, headers=header)
        if not resp.ok:
            break
        res = resp.json()
        total = res['total']
        stocks = res['stocks']
        for elem in stocks:
            if 'nmId' in elem and elem['nmId']:
                res_art_key[str(elem['nmId'])] = elem['barcode']
            if 'barcode' in elem and elem['barcode']:
                res_bar_key[str(elem['barcode'])] = elem['nmId']
        skip += take
    return res_art_key, res_bar_key


def get_prices_un(token, dt_since_str=None, dt_to_str=None) -> List:
    """
    Актуальный метод "Цены и скидки" (взамен отключённого 30.01.2025
    suppliers-api.wildberries.ru/public/api/v1/info).
    Возвращает по одной строке на каждый размер (sizeID) товара:
    price - цена продавца, discountedPrice - цена с учётом скидки продавца ("Цена в ЛК").
    ВАЖНО: подтверждено сверкой с реальными карточками в ЛК (nmID 1178158733,
    63 144.64 руб при скидке 48% => база 121 432 руб) - WB отдаёт эти поля уже
    в рублях, БЕЗ копеек. Деление на 100 не требуется.
    """
    header = get_header(token)
    url = "https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter"
    res = []
    limit = 1000
    offset = 0

    while True:
        params = {
            'limit': limit,
            'offset': offset,
        }
        resp = requests_get(url, headers=header, params=params)
        if not resp or not resp.ok:
            logging.warning('get_prices_un - WB API error')
            try:
                logging.warning(str(resp.text))
            except Exception as e:
                logging.warning(str(e))
            break

        try:
            goods = resp.json()['data']['listGoods']
        except Exception as e:
            logging.warning('get_prices_un - ' + str(e))
            break

        if not goods:
            break

        for good in goods:
            nm_id = good.get('nmID')
            for size in good.get('sizes', []):
                # Подтверждено сверкой с ЛК: WB отдаёт price/discountedPrice/clubDiscountedPrice
                # уже в рублях (не в копейках) - деление на 100 НЕ требуется
                res.append({
                    'nmID': nm_id,
                    'vendorCode': good.get('vendorCode'),
                    'sizeID': size.get('sizeID'),
                    'techSizeName': size.get('techSizeName'),
                    'price': size.get('price'),
                    'discountedPrice': size.get('discountedPrice'),
                    'clubDiscountedPrice': size.get('clubDiscountedPrice'),
                    'discount': good.get('discount'),
                    'clubDiscount': good.get('clubDiscount'),
                    'currencyIsoCode4217': good.get('currencyIsoCode4217'),
                })

        if len(goods) < limit:
            break
        offset += limit

    return res


def get_stat_stocks_un(token, last_hours=None) -> List:
    header = get_header(token)
    url = f"https://statistics-api.wildberries.ru/api/v1/supplier/stocks?key={token}"
    if last_hours:
        dt_now = datetime.datetime.now()
        dateFrom = (dt_now - datetime.timedelta(hours=last_hours)).strftime('%Y-%m-%dT%H:%M:00Z')
        url += f"&dateFrom={dateFrom}"

    resp = requests.get(url, headers=header)
    if resp:
        print(resp.text)
    if not resp or not resp.ok:
        return []
    try:
        res_dict = resp.json()
    except:
        return []
    return res_dict


def get_sales(token, dt_since_str, flag=0) -> List:
    url = f"https://statistics-api.wildberries.ru/api/v1/supplier/sales?dateFrom={dt_since_str}"
    header = get_header(token)
    res = []

    if flag:
        url += f"&flag={flag}"
    resp = requests_get(url, headers=header)
    if not resp or not resp.ok:
        logging.warning('WB API error')
        try:
            logging.warning(resp.text)
        except Exception as e:
            logging.warning(str(e))
        return res
    try:
        res = resp.json()
    except Exception as e:
        logging.warning(str(e))

    return res


def get_stocks(token, dt_since_str) -> List:
    url = f"https://statistics-api.wildberries.ru/api/v1/supplier/stocks?dateFrom={dt_since_str}"
    header = get_header(token)
    res = []

    resp = requests_get(url, headers=header)
    if not resp or not resp.ok:
        logging.warning('WB API error')
        try:
            logging.warning(resp.text)
        except Exception as e:
            logging.warning(str(e))
        return res
    try:
        res = resp.json()
    except Exception as e:
        logging.warning(str(e))

    return res


def get_cards_un(token, dt_since_str=None, dt_to_str=None):
    header = get_header(token)
    url = f"https://content-api.wildberries.ru/content/v2/get/cards/list"
    res = []
    updatedAt = None
    nmID = None
    limit = 100
    while True:
        data = {
                "settings": {
                    "cursor": {
                            "limit": limit
                        },
                    "filter": {
                            "withPhoto": -1
                        }
                }
        }
        if nmID:
            data['settings']['cursor']["nmID"] = nmID
        if updatedAt:
            data['settings']['cursor']["updatedAt"] = updatedAt
        try:
            resp = requests.post(url, headers=header, json=data)
            print(resp.text)
        except Exception as e:
            logging.warning(str(e))
            break

        print(resp.text)
        try:
            res_dict = resp.json()
            cards = res_dict["cards"]
        except Exception as e:
            logging.warning('get_cards_un-' + str(e))
            break
        # for card in cards:
        #     card['updateAt'] = card['updateAt'].replace('T', ' ').replace('Z', '')
        #     res.append(card)
        res.extend(cards)
        try:
            res_dict = resp.json()
            cursor = res_dict["cursor"]
        except Exception as e:
            logging.warning('get_cards_un-' + str(e))
            break
        updatedAt = cursor.get('updatedAt')
        nmID = cursor['nmID']
        total = cursor['total']
        # print(total)
        if total < limit:
            logging.info(f"get_cards_un-{total}<{limit}")
            break
    return res


def get_cards_un_v2(token, dt_since_str=None, dt_to_str=None):
    header = get_header(token)
    url = f"https://content-api.wildberries.ru/content/v2/get/cards/list"
    res = []
    updatedAt = None
    nmID = None
    limit = 100
    while True:
        data = {
                "settings": {
                    "cursor": {
                            "limit": limit
                        },
                    "filter": {
                            "withPhoto": -1
                        }
                }
        }
        if nmID:
            data['settings']['cursor']["nmID"] = nmID
        if updatedAt:
            data['settings']['cursor']["updatedAt"] = updatedAt
        try:
            resp = requests.post(url, headers=header, json=data)
            print(resp.text)
        except Exception as e:
            logging.warning(str(e))
            break

        print(resp.text)
        try:
            res_dict = resp.json()
            cards = res_dict["cards"]
        except Exception as e:
            logging.warning('get_cards_un-' + str(e))
            break
        # for card in cards:
        #     card['updateAt'] = card['updateAt'].replace('T', ' ').replace('Z', '')
        #     res.append(card)
        # res.extend(cards)
        for card in cards:
            append_flag = False
            for size in card.get('sizes', [{}]):
                for sku in size.get('skus', []):
                    if append_flag:
                        new_card = card.copy()
                        new_card['chrtID'] = size.get('chrtID')
                        new_card['techSize'] = size.get('techSize')
                        new_card['skus'] = str(sku)
                        res.append(new_card)
                    else:
                        card['chrtID'] = size.get('chrtID')
                        card['techSize'] = size.get('techSize')
                        card['skus'] = str(sku)
                        res.append(card)
                        append_flag = True
        try:
            res_dict = resp.json()
            cursor = res_dict["cursor"]
        except Exception as e:
            logging.warning('get_cards_un-' + str(e))
            break
        updatedAt = cursor.get('updatedAt')
        nmID = cursor['nmID']
        total = cursor['total']
        # print(total)
        if total < limit:
            # logging.info(f"get_cards_un-{total}<{limit}")
            break
    return res


def get_cart_cards_un_v2(token, dt_since_str=None, dt_to_str=None):
    header = get_header(token)
    url = f"https://content-api.wildberries.ru/content/v2/get/cards/trash"
    res = []
    trashedAt = None
    nmID = None
    limit = 100
    while True:
        data = {
                "settings": {
                    "cursor": {
                            "limit": limit
                        },
                }
        }
        if nmID:
            data['settings']['cursor']["nmID"] = nmID
        if trashedAt:
            data['settings']['cursor']["trashedAt"] = trashedAt
        try:
            resp = requests.post(url, headers=header, json=data)
        except Exception as e:
            logging.warning(str(e))
            break

        print(resp.text)
        try:
            res_dict = resp.json()
            cards = res_dict["cards"]
            cursor = res_dict["cursor"]
        except:
            break
        # for card in cards:
        #     card['updateAt'] = card['updateAt'].replace('T', ' ').replace('Z', '')
        #     res.append(card)
        # res.extend(cards)
        for card in cards:
            for size in card.get('sizes', [{}]):
                for sku in size.get('skus', []):
                    new_card = card.copy()
                    new_card['chrtID'] = size.get('chrtID')
                    new_card['techSize'] = size.get('techSize')
                    new_card['wbSize'] = size.get('wbSize') #???
                    new_card['skus'] = str(sku)
                    res.append(new_card)

        trashedAt = cursor.get('trashedAt')
        nmID = cursor['nmID']
        total = cursor['total']
        # print(total)
        if total < limit or not trashedAt:
            break
    return res


def get_cart_cards_un(token, dt_since_str=None, dt_to_str=None):
    header = get_header(token)
    url = f"https://content-api.wildberries.ru/content/v2/get/cards/trash"
    res = []
    trashedAt = None
    nmID = None
    limit = 100
    while True:
        data = {
                "settings": {
                    "cursor": {
                            "limit": limit
                        },
                }
        }
        if nmID:
            data['settings']['cursor']["nmID"] = nmID
        if trashedAt:
            data['settings']['cursor']["trashedAt"] = trashedAt
        try:
            resp = requests.post(url, headers=header, json=data)
        except Exception as e:
            logging.warning(str(e))
            break

        print(resp.text)
        try:
            res_dict = resp.json()
            cards = res_dict["cards"]
            cursor = res_dict["cursor"]
        except:
            break
        # for card in cards:
        #     card['updateAt'] = card['updateAt'].replace('T', ' ').replace('Z', '')
        #     res.append(card)
        res.extend(cards)
        trashedAt = cursor.get('trashedAt')
        nmID = cursor['nmID']
        total = cursor['total']
        # print(total)
        if total < limit or not trashedAt:
            break
    return res


def get_daily_stocks_un(token, dt_since_str, dt_to_str=None) -> list:
    res = get_stocks_un(token, dt_since_str, dt_to_str)
    date_txt = datetime.datetime.now().strftime(WB_DATE_FORMAT)
    for elem in res:
        elem['date'] = date_txt
    return res


def get_promos(token, dt_since_str, dt_to_str):
    # dt_to_str: "%Y-%m-%dT%H:%M:%S"
    # YYYY-MM-DDTHH:MM:SSZ
    # [{"id":1261,"name":"Отпускаем цены: финал распродажи - автоакция","startDateTime":"2025-06-14T21:00:00Z","endDateTime":"2025-06-18T20:59:59Z","type":"auto"},{"id":1258,"name...
    header = get_header(token)
    url = f"https://dp-calendar-api.wildberries.ru/api/v1/calendar/promotions"
    startDateTime = (datetime.datetime.strptime(dt_to_str, WB_DATETIME_FORMAT) + datetime.timedelta(days=2)).strftime(WB_DATETIME_FORMAT) + 'Z'
    endDateTime = (datetime.datetime.strptime(dt_to_str, WB_DATETIME_FORMAT) + datetime.timedelta(days=60)).strftime(WB_DATETIME_FORMAT) + 'Z'
    params = {
        "startDateTime": startDateTime,
        "endDateTime": endDateTime,
        "allPromo": False,
        "limit": 1000,
    }
    resp = requests_get(url, headers=header, params=params)
    if not resp:
        return []
    print(resp.text)
    print(header)
    try:
        cards = resp.json()["data"]["promotions"]
    except:
        return []
    else:
        return cards


def get_promo_products(token, promo_id):
    # dt_to_str: "%Y-%m-%dT%H:%M:%S"
    # YYYY-MM-DDTHH:MM:SSZ
    header = get_header(token)
    url = f"https://dp-calendar-api.wildberries.ru/api/v1/calendar/promotions/nomenclatures"
    params = {
        "promotionID": promo_id,
        'limit': 1000,
        "inAction": True,
    }
    resp = requests_get(url, headers=header, params=params)
    if not resp:
        return []
    print(resp.text)
    print(header)
    try:
        cards = resp.json()["data"]["nomenclatures"]
    except:
        return []
    else:
        return cards


def get_promo_products_un(token, dt_since_str, dt_to_str) -> list:
    promos = get_promos(token, dt_since_str, dt_to_str)
    res = []
    for elem in promos:
        # print(elem)
        promo_id = elem.get('id')
        if not promo_id:
            continue
        promo_products = get_promo_products(token, promo_id)
        # print(promo_products)
        for promo_product in promo_products:
            for key in elem:
                promo_product['action_'+key] = elem[key]
        res.extend(promo_products)
    return res


########################################################## Analytics new ############################################
def get_analytic_report_status(token, task_id):
    header = get_header(token)
    url = f"https://seller-analytics-api.wildberries.ru/api/v2/nm-report/downloads"
    params = {
        'filter': {
            'downloadIds': [task_id]
        }
    }
    resp = requests_get(url, headers=header, params=params)
    if not resp:
        return False
    if not resp.ok:
        logging.warning(str(resp.text))
        return False
    try:
        data_list = resp.json()['data']
    except Exception as e:
        logging.warning(str(e))
        return False
    status = ''
    for data in data_list:
        if data.get('id', '') == task_id:
            status = data.get('status', '')
            break

    return status == 'SUCCESS'


def get_analytic_report_done(token, task_id):
    """
    :param start_day: %Y-%m-%d
    """
    res = []
    header = get_header(token)
    url = f"https://seller-analytics-api.wildberries.ru/api/v2/nm-report/downloads/file/{task_id}"

    resp = requests.get(url, headers=header)
    if not resp:
        return res
    if not resp.ok:
        logging.warning(str(resp.text))
        return res

    zip_file_name = f"{task_id}.zip"
    zip_dir = os.path.join(DIR_DATA, 'analytic_report_temp')
    Path(zip_dir).mkdir(parents=True, exist_ok=True)
    zip_file_path = os.path.join(zip_dir, zip_file_name)
    try:
        with open(zip_file_path, 'wb') as f:
            f.write(resp.content)
        time.sleep(2)
    except Exception as e:
        logging.warning(f"get_analytic_report_done - {str(e)}")
        return res

    if not lib.unzip_files(zip_file_path, zip_dir):
        return res

    csv_file_path = os.path.join(zip_dir, f"{task_id}.csv")
    res = lib.read_csv(csv_file_path, delimiter=',')

    return res


def get_analytic_report_un(token, dt_since_str, dt_to_str) -> List:
    """
    "startDate": "2024-06-21",
    "endDate": "2024-06-23",
    """
    header = get_header(token)
    res = []
    id = str(uuid.uuid4())

    url = f"https://seller-analytics-api.wildberries.ru/api/v2/nm-report/downloads"
    data = {
        'id': id,
        'reportType': 'DETAIL_HISTORY_REPORT',
        'params': {
            'startDate': dt_since_str,
            'endDate': dt_to_str,
            'aggregationLevel': 'day'
        }

    }
    resp = requests_post(url, headers=header, data=data)

    if not resp:
        return res
    if not resp.ok:
        logging.warning(str(resp.text))
        return res

    limit = 20
    i = 0
    while not get_analytic_report_status(token, id):
        time.sleep(15)
        i += 1
        if i >= limit:
            logging.warning(f"Over limit get_storage_report_un - stop")
            break

    return get_analytic_report_done(token, id)


def get_media_adverts(token) -> List:
    # https://dev.wildberries.ru/docs/openapi/promotion#tag/Media/paths/~1adv~1v1~1adverts/get
    header = get_header(token)
    url = f"https://advert-media-api.wildberries.ru/adv/v1/adverts"
    res = []
    limit = 100
    offset = 0
    while True:
        params = {
            'limit': limit,
            'offset': offset,
            # 'status': 6 #6 — на показах, 4 — готова к запуску, 5 — запланирована, 7 — завершена, 10 — пауза по дневному лимиту/...
        }
        resp = requests_get(url, headers=header, params=params)
        try:
            adverts = resp.json()
            assert adverts
            assert adverts[0]['advertId']
        except Exception as e:
            logging.warning('get_media_adverts-' + str(e))
            try:
                logging.warning(str(resp.text))
            except:
                pass
            break

        res.extend(adverts)
        # {'advertId': 318550, 'name': 'Конфеты', 'brand': 'SweetStories', 'type': 2, 'status': 7, 'createTime': '2025-05-19T16:49:07.514911+03:00', 'endTime': '2025-05-22T00:01:12.785735Z'},
        offset += limit
        time.sleep(SLEEP_TIME_ANALYTICS)

    return res


def get_50_media_adverts_stat(token, adverts_ids, days, first_run=True) -> List:
    # https://dev.wildberries.ru/docs/openapi/promotion#tag/Statistika/paths/~1adv~1v1~1stats/post
    # days = ["2023-10-06", ....]
    if len(adverts_ids) > 50:
        adverts_ids = adverts_ids[:50]
    header = get_header(token)
    res = []

    url = f"https://advert-media-api.wildberries.ru/adv/v1/stats"
    body = []
    for adverts_id in adverts_ids:
        body.append(
            {
                'id': adverts_id,
                # 'dates': days
            }
        )

    resp = requests_post(url, headers=header, data=body)
    if not resp or not resp.ok:
        logging.warning(f"get_50_media_adverts_stat - {adverts_ids} error request")
        try:
            logging.warning(resp.text)
        except:
            pass
        return res

    try:
        stats = resp.json()
    except Exception as e:
        logging.warning(str(e))
        return res

    repeat_advs = []
    for main_stat in stats:
        if main_stat.get('error'):
            logging.warning(main_stat) #FIXME off
            if main_stat['error'] == 'Статистика в процессе получения':
                repeat_advs.append(main_stat['advert_id'])
        for stat in main_stat.get('stats', []):
            daily_stats = stat.get('daily_stats', [])
            for daily_stat in daily_stats:
                for key in stat:
                    if key == 'daily_stats':
                        continue
                    elif key == 'status':
                        daily_stat['item_status'] = stat['status']
                    elif key == 'views':
                        daily_stat['total_views'] = stat['views']
                    elif key == 'clicks':
                        daily_stat['total_clicks'] = stat['clicks']
                    else:
                        daily_stat[key] = stat[key]
                daily_stat['date'] = daily_stat.get('date', '').split('T')[0]
                for app_type_stat in daily_stat.get('app_type_stats', []):
                    for key in daily_stat:
                        if key != 'app_type_stats':
                            app_type_stat[key] = daily_stat[key]
                    res.append(app_type_stat)
    #             {'date': '2026-02-10T00:00:00+03:00', 'app_type_stats': [{'app_type': 1, 'stats': [{}]}, {'app_type': 32, 'stats': [{'views': 1}]}], 'item_id': 344831, 'item_name': 'Kortex', 'category_name': 'Контекстный баннер в поиске', 'advert_type': 1, 'place': 1, 'views': 1, 'date_from': '2025-11-01T17:46:49+03:00', 'date_to': '2026-02-10T13:16:48+03:00', 'subject_name': 'Амортизаторы автомобильные', 'item_status': 7, 'all_budget': 90000}

    # if repeat_advs and first_run: #FIXME - пока отключил тк нед док-в что 'Статистика в процессе получения' позволяет ее получить чуть позже
    #     time.sleep(15)
    #     res.extend(get_50_media_adverts_stat(token, repeat_advs, days, first_run=False))

    return res


def get_media_adverts_stat_un(token, dt_since_str=None, dt_to_str=None):
    res = []

    advs = get_media_adverts(token)
    adverts_ids = []
    ALLOWED_STATUSES = [6, 7, 8, 9, 10, 11] #https://dev.wildberries.ru/docs/openapi/promotion#tag/Media/paths/~1adv~1v1~1adverts/get
    for adv in advs:
        # {'advertId': 318550, 'name': 'Конфеты', 'brand': 'SweetStories', 'type': 2, 'status': 7, 'createTime': '2025-05-19T16:49:07.514911+03:00', 'endTime': '2025-05-22T00:01:12.785735Z'},
        if adv.get('status', 0) in ALLOWED_STATUSES:
            adverts_ids.append(adv['advertId'])
    # print(adverts_ids)
    #TODO - по кажд adv Надо получатьполные данные вмсете с Items и потом связывать item с advertId тк на выходе у нас толкьо item и не знаем advertId

    DT_FORMAT = "%Y-%m-%d"
    DATE_FROM_DAY = 21 #21
    DATE_PERIOD_DAYS = 7 #13
    days = []
    last_dt = datetime.datetime.now() - datetime.timedelta(days=DATE_FROM_DAY)
    cur_dt = last_dt
    while cur_dt >= last_dt - datetime.timedelta(days=DATE_PERIOD_DAYS):
        days.append(cur_dt.strftime(DT_FORMAT))
        cur_dt -= datetime.timedelta(days=1)
    # print(days)

    WB_ADVERT_ID_LIMIT = 50
    for j in range(0, len(adverts_ids), WB_ADVERT_ID_LIMIT):
        end_adverts_index = j + WB_ADVERT_ID_LIMIT
        if end_adverts_index >= len(adverts_ids):
            end_adverts_index = len(adverts_ids)
        adverts_ids_batch = adverts_ids[j:end_adverts_index]

        stats = get_50_media_adverts_stat(token, adverts_ids_batch, days) #TODO days - dont use!!
        res.extend(stats)
        time.sleep(SLEEP_TIME_REPORT)

    return res

# ============================================================
# ВРЕМЕННЫЙ ТЕСТОВЫЙ ЗАПУСК — чтобы увидеть РЕАЛЬНУЮ структуру ответа
# (раз в доке для v1 явно не показан пример с детализацией по дням,
#  нужно сначала глазами посмотреть, что реально прилетает)
# ============================================================
if __name__ == '__main__':
    import json
    import datetime

    TOKEN = "eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjYwMzAydjEiLCJ0eXAiOiJKV1QifQ.eyJhY2MiOjMsImVudCI6MSwiZXhwIjoxNzk1MDIwNzcyLCJmb3IiOiJzZWxmIiwiaWQiOiIwMTllNDNiYS1iZTZkLTcwMTQtYTk3OC0yMzMyMzJmODU5YjAiLCJpaWQiOjMzODM2NTAwLCJvaWQiOjQyMTM1MzcsInMiOjEwNzM3NTczMTAsInNpZCI6ImEwZTY0ODA5LTI0M2EtNDY1Yy1hNzkwLTBlZjk3Nzg5YmU0NiIsInQiOmZhbHNlLCJ1aWQiOjMzODM2NTAwfQ.Ek-JCzpB4hOMlVXC0vrDMRPinJDGBbPSZc4UZ9fgEUKLW-eHebB1oreL67oBFhT8tZlK6N2qdXajWZGrjF2HgA"  # тот же токен, что используется в main.py для wb.py
    dt_now = datetime.datetime.now()
    dt_to_str = dt_now.strftime(WB_DATETIME_FORMAT)
    dt_since_obj = dt_now - datetime.timedelta(hours=24*7)
    dt_since_str = dt_since_obj.strftime(WB_DATETIME_FORMAT)

    print("=== Шаг 1: список акций (get_promos) ===")
    promos = get_promos(TOKEN, dt_since_str, dt_to_str)
    print(f"Найдено акций: {len(promos)}")
    print(json.dumps(promos[:5], indent=2, ensure_ascii=False))

    if promos:
        promo_id = promos[0].get('id')
        print(f"\n=== Шаг 2: товары по акции id={promo_id} (get_promo_products) ===")
        products = get_promo_products(TOKEN, promo_id)
        print(f"Найдено товаров: {len(products)}")
        print(json.dumps(products[:5], indent=2, ensure_ascii=False))
    else:
        print("\nАкций не найдено — get_promo_products не тестируем")

    print("\n=== Шаг 3: цены и скидки (get_prices_un) ===")
    prices = get_prices_un(TOKEN)
    print(f"Найдено строк (nmID x размер): {len(prices)}")
    print(json.dumps(prices[:5], indent=2, ensure_ascii=False))