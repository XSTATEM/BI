# -- coding: utf-8 --
"""
Библиотека Озон

Автор: Олег Шабалов
Контакты: 89179021656, @olegshabalov
"""

import requests
import json
import datetime
import logging
import time
import math
import csv
import io


OZON_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.000Z"
OZON_DATE_FORMAT = "%Y-%m-%d"
OZON_RES_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
OZON_LIMIT = 1000
SLEEP_REPORT_TIME = 20
SLEEP_TIME = 5
TRY = 5
SLEEP_ANALITIC_TIME = 60


def get_headers(client_id, token):
    return {
        "Client-Id": str(client_id),
        "Api-Key": token,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }


def requests_post(url, headers=None, data=None):
    i = 0
    resp = None
    while i < TRY:
        try:
            resp = requests.post(url, headers=headers, json=data)
            json.loads(str(resp.text))
        except Exception as e:
            logging.warning(str(e) + f" - TRY{i}/{TRY}")
            time.sleep(SLEEP_TIME)
            i += 1
        else:
            if not resp.ok:
                logging.warning(str(resp.text) + f" - TRY{i}/{TRY}")
                time.sleep(SLEEP_TIME)
                i += 1
            else:
                break
    return resp


def requests_post_v2(url, headers=None, data=None, sleep_time=SLEEP_TIME):
    i = 0
    resp = None
    while i < TRY:
        try:
            resp = requests.post(url, headers=headers, json=data)
            json.loads(str(resp.text))
        except Exception as e:
            logging.warning(str(e) + f" - TRY{i}/{TRY}")
            time.sleep(sleep_time)
            i += 1
        else:
            if not resp.ok:
                logging.warning(str(resp.text) + f" - {url} - TRY{i}/{TRY}")
                time.sleep(sleep_time)
                i += 1
            else:
                break
    return resp


def get_orders_v2(delta, headers, schema='fbs'):
    """
    https://api-seller.ozon.ru/v3/posting/fbs/list
    :param delta:
    :param headers:
    :param schema:
    :return:
    """
    url = f"https://api-seller.ozon.ru/v3/posting/{schema}/list"
    offset = 0
    per_request = 100
    res = []
    dt = datetime.datetime.now() - datetime.timedelta(minutes=delta)
    date_since = dt.strftime(OZON_DATETIME_FORMAT)
    date_to = datetime.datetime.now().strftime(OZON_DATETIME_FORMAT)
    while True:
        data = {
            "limit": per_request,
            "offset": offset,
            "filter": {
                "since": date_since,
                "to": date_to,
                "status": ""
            },
            "with": {
                "analytics_data": True,
                "financial_data": True
            }
        }
        # resp = requests.post(url, headers=headers, json=data)
        # print(url)
        # print(headers)
        # print(data)
        # print('*'*50)
        resp = requests_post(url, headers=headers, data=data)
        # print(resp.text)
        try:
            res_list = json.loads(resp.text)["result"]["postings"]
        except:
            break
        if not res_list:
            break

        res.extend(res_list)
        offset += per_request
    return res


def get_orders_v3(dt_since_str, dt_to_str, headers, schema):
    url = f"https://api-seller.ozon.ru/v2/posting/{schema}/list"
    offset = 0
    per_request = OZON_LIMIT
    res = []
    while True:
        data = {
            "limit": per_request,
            "offset": offset,
            "filter": {
                "since": dt_since_str,
                "to": dt_to_str,
                # "status": ""
            },
            "with": {
                "analytics_data": True,
                "financial_data": True
            }
        }
        resp = requests_post(url, headers=headers, data=data)
        try:
            res_list = json.loads(resp.text)["result"]
        except:
            break
        if not res_list:
            break

        res.extend(res_list)
        offset += per_request
    return res


def get_stocks_v2(headers):
    per_request = OZON_LIMIT
    url = f"https://api-seller.ozon.ru/v3/product/info/stocks"
    raw_res = []
    last_id = ''
    while True:
        data = {
            "filter": {},
            "limit": per_request
        }
        if last_id:
            data['last_id'] = last_id
        resp = requests_post(url, headers=headers, data=data)
        # print(resp.text)
        try:
            res = json.loads(resp.text)["result"]
        except:
            break
        if not res.get('items'):
            break
        raw_res.extend(res.get('items'))
        last_id = res.get('last_id')

    return raw_res


def get_transactions_moments(dt_since_str, dt_to_str, headers, transaction_type='all', operation_types=[]):
    """
    Dict {order_number: transaction_date}
    """
    url = "https://api-seller.ozon.ru/v3/finance/transaction/list"
    page = 1
    per_request = 100
    res = []
    while True:
        filter = {
            "date": {
                "from": dt_since_str,
                "to": dt_to_str
            },
            "transaction_type": transaction_type
        }
        if operation_types:
            filter['operation_type'] = operation_types
        data = {
            "page_size": per_request,
            "page": page,
            "filter": filter
        }
        resp = requests.post(url, headers=headers, json=data)
        # print(resp.text)
        try:
            res_list = json.loads(resp.text)["result"]["operations"]
        except:
            break
        if not res_list:
            break
        res.extend(res_list)
        page += 1
    return res


def get_transactions_totals(headers, posting_number, dt_since_str=None, dt_to_str=None, transaction_type='all'):
    url = "https://api-seller.ozon.ru/v3/finance/transaction/totals"
    res = []

    data = {
        # "date": {
        #     "from": dt_since_str,
        #     "to": dt_to_str
        # },
        "posting_number": posting_number,
        "transaction_type": transaction_type
    }
    resp = requests.post(url, headers=headers, json=data)
    # print(resp.text)
    try:
        res = json.loads(resp.text)["result"]
    except Exception as e:
        logging.warning(str(e))

    return res


def get_transactions_moments_un(headers, dt_since_str, dt_to_str, transaction_type='all', operation_types=[]):
    """
    Dict {order_number: transaction_date}
    datetime.datetime.strptime(dt_to_str, OZON_DATETIME_FORMAT) - datetime.datetime.strptime(dt_since_str, OZON_DATETIME_FORMAT)
    """
    url = "https://api-seller.ozon.ru/v3/finance/transaction/list"
    page = 1
    per_request = 100
    res = []
    while True:
        filter = {
            "date": {
                "from": dt_since_str,
                "to": dt_to_str
            },
            "transaction_type": transaction_type
        }
        if operation_types:
            filter['operation_type'] = operation_types
        data = {
            "page_size": per_request,
            "page": page,
            "filter": filter
        }
        resp = requests_post(url, headers=headers, data=data)
        try:
            res_list = json.loads(resp.text)["result"]["operations"]
        except Exception as e:
            logging.warning(str(e))
            # logging.warning(str(resp.text))
            break
        if not res_list:
            break
        res.extend(res_list)
        page += 1
    return res


def get_transactions_moments_un_v2(headers, dt_since_str, dt_to_str, transaction_type='all', operation_types=[]):
    """
    Dict {order_number: transaction_date}
    datetime.datetime.strptime(dt_to_str, OZON_DATETIME_FORMAT) - datetime.datetime.strptime(dt_since_str, OZON_DATETIME_FORMAT)
    """
    url = "https://api-seller.ozon.ru/v3/finance/transaction/list"
    per_request = 100
    res = []
    delta_hourse = 12

    dt_to_obj = datetime.datetime.strptime(dt_to_str, OZON_DATETIME_FORMAT)
    dt_since_obj = datetime.datetime.strptime(dt_since_str, OZON_DATETIME_FORMAT)
    dt_local_to_obj = dt_since_obj + datetime.timedelta(hours=delta_hourse)
    while dt_since_obj < dt_to_obj:
        page = 1
        while True:
            filter = {
                "date": {
                    "from": dt_since_obj.strftime(OZON_DATETIME_FORMAT),
                    "to": dt_local_to_obj.strftime(OZON_DATETIME_FORMAT)
                },
                "transaction_type": transaction_type
            }
            if operation_types:
                filter['operation_type'] = operation_types
            data = {
                "page_size": per_request,
                "page": page,
                "filter": filter
            }
            resp = requests_post(url, headers=headers, data=data)
            try:
                res_list = json.loads(resp.text)["result"]["operations"]
            except Exception as e:
                logging.warning(str(e))
                # logging.warning(str(resp.text))
                break
            if not res_list:
                break
            res.extend(res_list)
            page += 1
        dt_since_obj += datetime.timedelta(hours=delta_hourse)
        dt_local_to_obj += datetime.timedelta(hours=delta_hourse)
    return res


def get_stocks_report_un(headers, dt_since_str, dt_to_str):
    url = f"https://api-seller.ozon.ru/v2/analytics/stock_on_warehouses"
    offset = 0
    per_request = 100

    ozon_stocks_raw = []
    while True:
        data = {
            "limit": per_request,
            "offset": offset
        }
        resp = requests_post_v2(url, headers=headers, data=data, sleep_time=20)
        # print(resp.text)
        # {
        # "free_to_sell_amount": 0,
        # "item_code": "string",
        # "item_name": "string",
        # "promised_amount": 0,
        # "reserved_amount": 0,
        # "sku": 0,
        # "warehouse_name": "string"
        # }
        try:
            wh_list = json.loads(resp.text)["result"]["rows"]
        except:
            break
        if not wh_list:
            break
        # for wh in wh_list:
        #     for item in wh['items']:
        #         item['warehouse_id'] = wh['id']
        #         item['warehouse_name'] = wh['name']
        #         res.append(item)
        # logging.info(f"Recieved {len(wh_list)} ozon stocks")
        ozon_stocks_raw.extend(wh_list)
        # time.sleep(2)
        # print(wh_list)
        # sys.exit()
        offset += per_request

    return ozon_stocks_raw


def get_daily_stocks_report_un(headers, dt_since_str, dt_to_str):
    res = get_stocks_report_un(headers, dt_since_str, dt_to_str)
    date_txt = datetime.datetime.now().strftime(OZON_DATE_FORMAT)
    for elem in res:
        elem['date'] = date_txt
    return res


def get_report_by_code(headers, code):
    url = "https://api-seller.ozon.ru/v1/report/info"
    data = {
        "code": code
    }
    resp = requests.post(url, headers=headers, json=data)
    # print(resp.text)
    if not resp.ok:
        logging.info("API error")
        return ''
    try:
        res_dict = json.loads(resp.text)
        if res_dict['result']['status'] == 'failed':
            logging.warning(res_dict['result']['error'])
            return None
        return res_dict['result']['file']
    except:
        logging.info("API error")
        return ''


def get_file(headers, file_url):
    url = file_url
    file_name = file_url.split('/')[-1]
    resp = requests.get(url, headers=headers)
    # print(resp.text)
    if not resp.ok:
        logging.info("API error")
        return None
    try:
        with open(file_name, 'wb') as f:
            f.write(resp.content)
        return file_name
    except:
        logging.info("API error")
        return None


def open_file_to_dict(headers, file_url) -> list:
    url = file_url
    file_name = file_url.split('/')[-1]
    # headers['']
    resp = requests.get(url, headers=headers)
    resp.encoding = 'utf-8'
    # print(str(resp.text).encode('cp1251', 'ignore').decode('cp1251'))
    res = []
    if not resp.ok:
        logging.info("API error")
        return res
    try:
        buff = io.StringIO(resp.text.replace('\ufeff', ''))
        dr = csv.DictReader(buff, delimiter=';')
        for row in dr:
            res.append(row)
    except:
        logging.info('CSV read error')

    return res


def get_fbo_orders_report_un(headers, date_from=None, date_to=None):
    """
    ГГГГ-ММ-ДД
    """
    url = "https://api-seller.ozon.ru/v1/report/postings/create"
    data = {
        "filter": {
            "processed_at_from": date_from + "T00:00:00.861Z",
            "processed_at_to": date_to + "T00:00:00.861Z",
            "delivery_schema": [
                # "fbs",
                "fbo",
                # "crossborder"
            ],
        },
        "language": "DEFAULT"
    }
    resp = requests.post(url, headers=headers, json=data)
    # logging.info(resp.text)
    if not resp.ok:
        logging.warning("API error")
        return []
    try:
        res_dict = json.loads(resp.text)
        code = res_dict['result']['code']
    except:
        logging.warning("API error")
        return []

    if code:
        i = 0
        while True:
            time.sleep(SLEEP_REPORT_TIME)
            file = get_report_by_code(headers, code)
            # print(file)
            if file:
                logging.info("Отчет готов - скачиваем!")
                return open_file_to_dict(headers, file)
            logging.info(f'Отчет еще не готов, след проверка через {SLEEP_REPORT_TIME}сек')
            i += 1
            if TRY and i >= TRY:
                logging.info(f'Сделали {TRY} попыток - break')
                break

    return []


def get_fbs_orders_report_un(headers, date_from=None, date_to=None):
    """
    ГГГГ-ММ-ДД
    """
    url = "https://api-seller.ozon.ru/v1/report/postings/create"
    data = {
        "filter": {
            "processed_at_from": date_from + "T00:00:00.861Z",
            "processed_at_to": date_to + "T00:00:00.861Z",
            "delivery_schema": [
                "fbs",
                # "fbo",
                # "crossborder"
            ],
        },
        "language": "DEFAULT"
    }
    resp = requests.post(url, headers=headers, json=data)
    # logging.info(resp.text)
    if not resp.ok:
        logging.warning("API error")
        return []
    try:
        res_dict = json.loads(resp.text)
        code = res_dict['result']['code']
    except:
        logging.warning("API error")
        return []

    if code:
        i = 0
        while True:
            time.sleep(SLEEP_REPORT_TIME)
            file = get_report_by_code(headers, code)
            # print(file)
            if file:
                logging.info("Отчет готов - скачиваем!")
                return open_file_to_dict(headers, file)
            logging.info(f'Отчет еще не готов, след проверка через {SLEEP_REPORT_TIME}сек')
            i += 1
            if TRY and i >= TRY:
                logging.info(f'Сделали {TRY} попыток - break')
                break

    return []


def get_products_report_un(headers, dt_since_str=None, dt_to_str=None):
    url = "https://api-seller.ozon.ru/v1/report/products/create"
    data = {
        "language": "DEFAULT",
        "visibility": "ALL"
    }
    resp = requests.post(url, headers=headers, json=data)
    # print(resp.text)
    if not resp.ok:
        logging.info("API error")
        return []
    try:
        res_dict = json.loads(resp.text)
        code = res_dict['result']['code']
    except:
        logging.info("API error")
        return []

    if code:
        i = 0
        while True:
            time.sleep(SLEEP_ANALITIC_TIME)
            file = get_report_by_code(headers, code)
            if file:
                logging.info("get_products_report_un - отчет готов - скачиваем!")
                return open_file_to_dict(headers, file)
            logging.info(f'get_products_report_un - отчет еще не готов, след проверка через {SLEEP_ANALITIC_TIME}сек')
            i += 1
            if TRY and i >= TRY:
                logging.info(f'get_products_report_un - сделали {TRY} попыток - break')
                break

    return []


def get_fbo_orders_un(headers, dt_since_str, dt_to_str):
    url = "https://api-seller.ozon.ru/v2/posting/fbo/list"
    offset = 0
    per_request = 100
    res = []

    while True:
        data = {
            "dir": "ASC",
            "limit": per_request,
            "offset": offset,
            "filter": {
                "since": dt_since_str,
                "status": "",
                "to": dt_to_str
            },
            "with": {
                "analytics_data": True,
                "financial_data": True
            }
        }
        resp = requests_post(url, headers=headers, data=data)
        # print(resp.text)

        try:
            res_list = json.loads(resp.text)["result"]
        except:
            break
        if not res_list:
            break

        res.extend(res_list)
        offset += per_request
    return res


def get_fbo_orders_v2_un(headers, dt_since_str, dt_to_str):
    url = "https://api-seller.ozon.ru/v2/posting/fbo/list"
    offset = 0
    per_request = 100
    res = []

    while True:
        data = {
            "dir": "ASC",
            "limit": per_request,
            "offset": offset,
            "filter": {
                "since": dt_since_str,
                "status": "",
                "to": dt_to_str
            },
            "with": {
                "analytics_data": True,
                "financial_data": True
            }
        }
        resp = requests_post(url, headers=headers, data=data)
        # print(resp.text)

        try:
            res_list = json.loads(resp.text)["result"]
        except:
            break
        if not res_list:
            break

        res.extend(res_list)
        offset += per_request

    final_res = []
    for elem in res:
        products = elem.get('products', [])
        financial_data_products = elem.get('financial_data', {}).get('products', [])
        for i, product in enumerate(products):
            new_elem = elem.copy()
            for key in product:
                new_elem[key] = product[key]
            if i < len(financial_data_products):
                for key in financial_data_products[i]:
                    new_elem[key] = financial_data_products[i][key]
                if financial_data_products[i].get('item_services'):
                    for key in financial_data_products[i].get('item_services', {}):
                        new_elem[key] = financial_data_products[i]['item_services'][key]

            final_res.append(new_elem)
    return final_res


def get_fbs_orders_un(headers, dt_since_str, dt_to_str):
    url = f"https://api-seller.ozon.ru/v3/posting/fbs/list"
    offset = 0
    per_request = 100
    res = []
    while True:
        data = {
            "limit": per_request,
            "offset": offset,
            "filter": {
                "since": dt_since_str,
                "to": dt_to_str,
                "status": ""
            },
            "with": {
                "analytics_data": True,
                "financial_data": True
            }
        }
        resp = requests_post(url, headers=headers, data=data)
        # print(resp.text)
        try:
            res_list = json.loads(resp.text)["result"]["postings"]
        except:
            break
        if not res_list:
            break

        res.extend(res_list)
        offset += per_request
    return res


def get_fbs_orders_v2_un(headers, dt_since_str, dt_to_str):
    url = f"https://api-seller.ozon.ru/v3/posting/fbs/list"
    offset = 0
    per_request = 100
    res = []
    while True:
        data = {
            "limit": per_request,
            "offset": offset,
            "filter": {
                "since": dt_since_str,
                "to": dt_to_str,
                "status": ""
            },
            "with": {
                "analytics_data": True,
                "financial_data": True
            }
        }
        resp = requests_post(url, headers=headers, data=data)
        # print(resp.text)
        try:
            res_list = json.loads(resp.text)["result"]["postings"]
        except:
            break
        if not res_list:
            break

        res.extend(res_list)
        offset += per_request

    final_res = []
    for elem in res:
        products = elem.get('products', [])
        financial_data_products = elem.get('financial_data', {}).get('products', [])
        for i, product in enumerate(products):
            new_elem = elem.copy()
            for key in product:
                new_elem[key] = product[key]
            if i < len(financial_data_products):
                for key in financial_data_products[i]:
                    new_elem[key] = financial_data_products[i][key]
                if financial_data_products[i].get('item_services'):
                    for key in financial_data_products[i].get('item_services', {}):
                        new_elem[key] = financial_data_products[i]['item_services'][key]

            final_res.append(new_elem)
    return final_res


def get_analitics_data_un(headers, dt_since_str, dt_to_str):
    """
    "date_from": "2020-09-01"

    """
    url = f"https://api-seller.ozon.ru/v1/analytics/data"
    offset = 0
    per_request = 1000
    res = []
    metrics = [
        'revenue',
        'ordered_units',
        'hits_view',
        'hits_tocart',
        'session_view',
        # 'conv_tocart',
        'returns',
        'cancellations',
        'delivered_units',
        'position_category',
        'hits_view_search',
        'hits_view_pdp',
        'hits_tocart_search',
        'hits_tocart_pdp'
    ]
    dimension = [
        "sku",
        "day"
    ]
    while True:
        data = {
            "limit": per_request,
            "offset": offset,
            "date_from": dt_since_str,
            "date_to": dt_to_str,
            "dimension": dimension,
            "metrics": metrics
        }
        resp = requests_post_v2(url, headers=headers, data=data, sleep_time=SLEEP_ANALITIC_TIME)
        # print(resp.text)
        try:
            res_list = json.loads(resp.text)["result"]["data"]
        except Exception as e:
            # logging.warning(str(e))
            break
        if not res_list:
            break

        res.extend(res_list)
        offset += per_request

    ### prepare list of dicts
    result = []
    for elem in res:
        elem_dict = dict()
        for i, subelem in enumerate(elem.get('dimensions', [])):
            elem_dict[dimension[i]] = subelem['id']
            if dimension[i] == 'sku':
                elem_dict['name'] = subelem['name']
        for i, subelem in enumerate(elem.get('metrics', [])):
            elem_dict[metrics[i]] = subelem
        result.append(elem_dict)

    return result


def get_finance_realization_un(headers, dt_since_str, dt_to_str):
    """
    Dict {order_number: transaction_date}
    """
    dt_m_y = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%m-%Y")
    m_int = int(dt_m_y.split('-')[0].lstrip('0'))
    y_int = int(dt_m_y.split('-')[1])
    url = "https://api-seller.ozon.ru/v2/finance/realization"
    data = {
        "month": m_int,
        "year": y_int
    }
    resp = requests_post(url, headers=headers, data=data)
    try:
        result = json.loads(resp.text)["result"]
        res_list = result['rows']
        header = result['header']
    except Exception as e:
        logging.warning(str(e))
        return []
    for elem in res_list:
        elem['number'] = header.get("header")
        elem['start_date'] = header.get("start_date")
        elem['stop_date'] = header.get("stop_date")

    return res_list


def get_finance_realization_un_v2(headers, dt_since_str, dt_to_str):
    """
    Dict {order_number: transaction_date}
    """
    try:
        delta_days = (datetime.datetime.strptime(dt_to_str, OZON_DATETIME_FORMAT) - datetime.datetime.strptime(dt_since_str, OZON_DATETIME_FORMAT)).days
    except Exception as e:
        logging.warning(f"get_finance_realization_un_v2 - {str(e)}")
        delta_days = 30

    last_months = math.ceil(delta_days / 30)
    logging.info(f"get_finance_realization_un_v2 - last_months = {last_months}")

    res = []
    for i in range(last_months):
        dt_m_y = (datetime.datetime.now() - datetime.timedelta(days=30 * (i+1))).strftime("%m-%Y")
        m_int = int(dt_m_y.split('-')[0].lstrip('0'))
        y_int = int(dt_m_y.split('-')[1])
        url = "https://api-seller.ozon.ru/v2/finance/realization"
        data = {
            "month": m_int,
            "year": y_int
        }
        resp = requests_post(url, headers=headers, data=data)
        try:
            result = json.loads(resp.text)["result"]
            res_list = result['rows']
            header = result['header']
        except Exception as e:
            logging.warning(str(e))
            continue
        for elem in res_list:
            elem['number'] = header.get("header")
            elem['start_date'] = header.get("start_date")
            elem['stop_date'] = header.get("stop_date")
        res.extend(res_list)

    return res


def get_b2b_report_un(headers, dt_since_str=None, dt_to_str=None):
    dt_m_y = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%Y-%m") #TODO - период больше 1 месяца
    url = "https://api-seller.ozon.ru/v1/finance/document-b2b-sales"
    data = {
        "language": "DEFAULT",
        "date": dt_m_y
    }
    resp = requests.post(url, headers=headers, json=data)
    # print(resp.text)
    if not resp.ok:
        logging.info("API error")
        return []
    try:
        res_dict = json.loads(resp.text)
        code = res_dict['result']['code']
    except:
        logging.info("API error")
        return []

    if code:
        i = 0
        while True:
            time.sleep(SLEEP_REPORT_TIME)
            file = get_report_by_code(headers, code)
            # print(file)
            if file:
                logging.info("get_b2b_report_un - отчет готов - скачиваем!")
                return open_file_to_dict(headers, file)
            logging.info(f'get_b2b_report_un - отчет еще не готов, след проверка через {SLEEP_REPORT_TIME}сек')
            i += 1
            if TRY and i >= TRY:
                logging.info(f'get_b2b_report_un - сделали {TRY} попыток - break')
                break

    return []


def get_balance_report_un(headers, dt_since_str=None, dt_to_str=None):
    dt_m_y = (datetime.datetime.now() - datetime.timedelta(days=30*2)).strftime("%Y-%m") #TODO - период больше 1 месяца
    url = "https://api-seller.ozon.ru/v1/finance/mutual-settlement"
    data = {
        "language": "DEFAULT",
        "date": dt_m_y
    }
    resp = requests.post(url, headers=headers, json=data)
    # print(resp.text)
    if not resp.ok:
        logging.info("API error")
        return []
    try:
        res_dict = json.loads(resp.text)
        code = res_dict['result']['code']
    except:
        logging.info("API error")
        return []

    if code:
        i = 0
        while True:
            time.sleep(SLEEP_REPORT_TIME)
            file = get_report_by_code(headers, code)
            # print(file)
            if file:
                logging.info("get_b2b_report_un - отчет готов - скачиваем!")
                return open_file_to_dict(headers, file)
            logging.info(f'get_b2b_report_un - отчет еще не готов, след проверка через {SLEEP_REPORT_TIME}сек')
            i += 1
            if TRY and i >= TRY:
                logging.info(f'get_b2b_report_un - сделали {TRY} попыток - break')
                break

    return []


def get_1000_products_info(headers, offer_ids_str_list):
    # https://docs.ozon.ru/api/seller/#operation/ProductAPI_GetProductInfoList
    url = "https://api-seller.ozon.ru/v3/product/info/list"
    items = []
    data = {
        "offer_id": offer_ids_str_list,
    }
    resp = requests.post(url, headers=headers, json=data)
    # logging.info(resp.text)
    if not resp.ok:
        logging.warning('get_prices_by_offer_ids_new - ' + resp.text)
        return items
    try:
        res_dict = json.loads(resp.text)
        items = res_dict['items']
    except Exception as e:
        logging.warning('get_prices_by_offer_ids_new - ' + str(e))
    return items


def get_stocks_v4(headers):
    url = f"https://api-seller.ozon.ru/v4/product/info/stocks"
    per_request = 1000
    raw_res = []
    cursor = ''
    while True:
        data = {
            "filter": {},
            "limit": per_request
        }
        if cursor:
            data['cursor'] = cursor
        resp = requests.post(url, headers=headers, json=data)
        # print(resp.text)
        try:
            res = json.loads(resp.text)
        except:
            break
        if not res.get('items'):
            break
        raw_res.extend(res.get('items'))
        cursor = res.get('cursor')

    return raw_res


def get_prices_v5_un(headers, dt_since_str=None, dt_to_str=None) -> list:
    """
    Метод "Информация о цене товара" (v5/product/info/prices).
    Отдаёт цену, установленную продавцом в ЛК: price - текущая цена,
    old_price - цена до скидки (зачёркнутая), min_price/premium_price/recommended_price.
    ВАЖНО: поле marketing_price (примерная цена с учётом акций Ozon) отключено Ozon 12.11.2025,
    поэтому "реальную" цену покупателя через API получить нельзя - берём только цену из ЛК.
    """
    url = "https://api-seller.ozon.ru/v5/product/info/prices"
    per_request = 1000
    res = []
    cursor = ''

    while True:
        data = {
            "filter": {"visibility": "ALL"},
            "limit": per_request
        }
        if cursor:
            data['cursor'] = cursor
        resp = requests.post(url, headers=headers, json=data)
        try:
            res_dict = json.loads(resp.text)
        except Exception as e:
            logging.warning('get_prices_v5_un - ' + str(e))
            break

        items = res_dict.get('items')
        if not items:
            break

        for item in items:
            price = item.get('price', {}) or {}
            res.append({
                'offer_id': item.get('offer_id'),
                'product_id': item.get('product_id'),
                'price': price.get('price'),
                'old_price': price.get('old_price'),
                'min_price': price.get('min_price'),
                'premium_price': price.get('premium_price'),
                'recommended_price': price.get('recommended_price'),
                'vat': price.get('vat'),
                'currency_code': price.get('currency_code'),
                'auto_action_enabled': price.get('auto_action_enabled'),
            })

        new_cursor = res_dict.get('cursor')
        if not new_cursor or new_cursor == cursor:
            break
        cursor = new_cursor

    return res


def get_daily_prices_v5_un(headers, dt_since_str=None, dt_to_str=None) -> list:
    """
    То же самое, что get_prices_v5_un, но с меткой даты - для историчной таблицы цен
    (по аналогии с get_daily_stocks_report_un/get_stocks_report_un).
    """
    res = get_prices_v5_un(headers, dt_since_str, dt_to_str)
    date_txt = datetime.datetime.now().strftime(OZON_DATE_FORMAT)
    for elem in res:
        elem['date'] = date_txt
    return res


def make_ozon_types_dict(result_dict, ozon_categories):
    for elem in ozon_categories:
        if elem.get("disabled"):
            continue
        # if elem.get('category_name'):
        #     logging.info(f"{elem['category_name']} - category")
        if elem['children'] and elem['children'][0].get('description_category_id'):
            make_ozon_types_dict(result_dict, elem['children'])
            # result_dict[elem['description_category_id']] = elem['category_name']
        else:
            for type_children in elem['children']:
                # result_dict.append(f"{elem['description_category_id']}/{type_children['type_id']}-{type_children['type_name']}-{elem['category_name']}")
                # result_dict[type_children['type_name'].lower()] = type_children['type_id']
                result_dict[type_children['type_id']] = {
                    'type_name': type_children['type_name'],
                    'description_category_id': elem['description_category_id'],
                    'description_category_name': elem['category_name'],
                }
                # logging.info(f"{type_children['type_name']} - type")
                if type_children['children'] and type_children['children'][0]:
                    make_ozon_types_dict(result_dict, type_children['children'])
    return


def get_categories_tree(headers):
    url = "https://api-seller.ozon.ru/v1/description-category/tree"
    resp = requests.post(url, headers=headers)
    # print(resp.text)
    res = {}
    if resp.ok:
        try:
            res = json.loads(resp.text)['result']
        except:
            pass
    types_dict = {}
    make_ozon_types_dict(types_dict, res)
    return types_dict


def get_categories_un(headers, dt_since_str=None, dt_to_str=None):
    ozon_get_limit = 1000
    raw_stocks = get_stocks_v4(headers)
    offer_ids = [str(elem['offer_id']) for elem in raw_stocks]
    catdata_by_typeid = dict()
    for i in range(0, len(offer_ids), ozon_get_limit):
        end_index = i + ozon_get_limit
        if end_index >= len(offer_ids):
            end_index = len(offer_ids)
        offer_ids_batch = offer_ids[i:end_index]
        products = get_1000_products_info(headers, offer_ids_batch)
        for product in products:
            description_category_id = product.get('description_category_id')
            type_id = product.get('type_id')
            if type_id not in catdata_by_typeid:
                catdata_by_typeid[type_id] = {
                    'description_category_id': None,
                    'count': 0
                }
            catdata_by_typeid[type_id]['description_category_id'] = description_category_id
            catdata_by_typeid[type_id]['count'] += 1

    ozon_types_dict = get_categories_tree(headers)
    res = []
    for type_id in catdata_by_typeid:
        res.append(
            {
                'type_id': type_id,
                'description_category_id': catdata_by_typeid[type_id]['description_category_id'],
                'type_name': ozon_types_dict.get(type_id, {}).get('type_name', ''),
                'description_category_name': ozon_types_dict.get(type_id, {}).get('description_category_name', ''),
                'products': catdata_by_typeid[type_id]['count'],
            }
        )

    return res


def get_categories_v2_un(headers, dt_since_str=None, dt_to_str=None):
    ozon_get_limit = 1000
    raw_stocks = get_stocks_v4(headers)
    offer_ids = [str(elem['offer_id']) for elem in raw_stocks]
    res = []
    for i in range(0, len(offer_ids), ozon_get_limit):
        end_index = i + ozon_get_limit
        if end_index >= len(offer_ids):
            end_index = len(offer_ids)
        offer_ids_batch = offer_ids[i:end_index]
        products = get_1000_products_info(headers, offer_ids_batch)
        for product in products:
            description_category_id = product.get('description_category_id')
            type_id = product.get('type_id')
            name = product.get('name')
            offer_id = product.get('offer_id')
            if offer_id:
                res.append(
                    {
                        'offer_id': offer_id,
                        'name': name,
                        'description_category_id': description_category_id,
                        'type_id': type_id,
                    }
                )

    ozon_types_dict = get_categories_tree(headers)
    for elem in res:
        elem['type_name'] = ozon_types_dict.get(elem['type_id'], {}).get('type_name', '')
        elem['description_category_name'] = ozon_types_dict.get(elem['type_id'], {}).get('description_category_name', '')

    return res


def get_stocks_analytic_un(headers, dt_since_str=None, dt_to_str=None):
    raw_stocks = get_stocks_v4(headers)
    skus = set()
    for raw_stock in raw_stocks:
        for elem in raw_stock.get('stocks', []):
            if elem.get('sku'):
                skus.add(elem['sku'])
    skus = list(skus)
    ozon_get_limit = 100

    res = []
    for i in range(0, len(skus), ozon_get_limit):
        end_index = i + ozon_get_limit
        if end_index >= len(skus):
            end_index = len(skus)
        skus_batch = skus[i:end_index]
        data = {
            "skus": skus_batch
        }
        url = "https://api-seller.ozon.ru/v1/analytics/stocks"
        resp = requests.post(url, headers=headers, json=data)
        # print(resp.text)
        try:
            items = json.loads(resp.text)['items']
        except:
            continue
        res.extend(items)

    return res
