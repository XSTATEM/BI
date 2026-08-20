# -*- coding: utf-8 -*-
"""
Yandex API lib
"""
import datetime

import requests
import logging
import json
import time

TRY = 3
SLEEP_TIME = 2
YANDEX_API_PAUSE = 30
YANDEX_DATE_FORMAT = '%d-%m-%Y'
YANDEX_REQUEST_DATE_FORMAT = '%Y-%m-%d'

YANDEX_TOKEN = 'y0_AgAAAAAL5cSPAAkv_gAAAADdKB6DKzwAAfJZQh-FD3bUgsImjeIQeY0'
YANDEX_CLIENT_ID = 'ce63424dad194593aaf4d36bb7eb16e2'
YANDEX_HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'Authorization': f'OAuth oauth_token={YANDEX_TOKEN}, oauth_client_id={YANDEX_CLIENT_ID}'
}

def requests_get(url, headers=None):
    i = 0
    resp = None
    while i < TRY:
        try:
            resp = requests.get(url, headers=headers)
        except Exception as e:
            logging.warning('Error making GET request to Sima, try again')
            logging.warning(str(e))
            time.sleep(SLEEP_TIME)
            i += 1
        else:
            if resp:
                break
            logging.warning(f'Empty response from url {url} - {resp}, try again')
            time.sleep(SLEEP_TIME)
            i += 1
    return resp


def requests_get_params(url, params=None, headers=None):
    i = 0
    resp = None
    while i < TRY:
        try:
            resp = requests.get(url, params=params, headers=headers)
            # print(resp.text)
        except Exception as e:
            logging.warning('Error making GET request to Sima, try again')
            logging.warning(str(e))
            time.sleep(SLEEP_TIME)
            i += 1
        else:
            if resp:
                break
            logging.warning(f'Empty response from url {url} - {resp}, try again')
            time.sleep(SLEEP_TIME)
            i += 1
    return resp


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


def get_prices_temp(headers, campaign_id):
    base_url = f'https://api.partner.market.yandex.ru/v2/campaigns/{campaign_id}/offer-prices.json'
    resp = requests_get(base_url, headers=headers)
    print(resp.text)


def get_prices(headers, campaign_id):
    base_url = f'https://api.partner.market.yandex.ru/v2/campaigns/{campaign_id}/offer-prices.json?limit=2000'
    url = base_url
    # res = []
    res2 = dict()
    stop_flag = False

    while True:
        resp = requests_get(url, headers=headers)
        try:
            res_dict = json.loads(resp.text)['result']
        except:
            break
        # print(res_dict)

        next_page = None
        if 'paging' in res_dict:
            next_page = res_dict['paging'].get('nextPageToken')

        if res_dict.get('offers'):
            for elem in res_dict['offers']:
                id = elem.get('id')
                if id in res2:
                    stop_flag = True
                    break
                res2[id] = elem.get('marketSku')

        if next_page:
            url = base_url + f'&page_token={next_page}'
        else:
            break

        if stop_flag:
            break

    return res2
    # print(len(res2))


def set_prices(headers, campaign_id, prices: dict, batch_size: int):
    """
    :param prices: utm_term: str (yandex_id: str) -> (sku: str, mpn: str or None, price: str, price_old: str, price_wholesale: str, quantity: int)
    """
    batch = []
    i = 0
    final = set()
    for id in prices:
        if i and i % batch_size == 0:
            url = f'https://api.partner.market.yandex.ru/v2/campaigns/{campaign_id}/offer-prices/updates.json'
            data = {
                'offers': batch
            }
            trys = 0
            res = None
            while True:
                if trys >= TRY:
                    break
                try:
                    res = requests.post(url, headers=headers, json=data)
                except Exception as e:
                    logging.warning(str(e))
                    pass
                else:
                    if res:
                        logging.info(res.text)
                        for batch_elem in batch:
                            final.add(batch_elem['id'])
                        break
                trys += 1
                logging.warning(f"Error offer-prices/updates.json request. Sleep for {YANDEX_API_PAUSE}")
                time.sleep(YANDEX_API_PAUSE)
            batch = []
            i = 0

        else:
            try:
                price = float(prices[id][2])
                price_old = float(prices[id][3])
            except:
                continue
            if (price_old - price) / price_old < 0.1:
                price_old = round(price * 1.1, 0)
            batch.append(
                {
                    'id': id,
                    'price': {
                        'currencyId': "RUR",
                        'value': price,
                        'discountBase': price_old,
                        "vat": 6
                    }
                }
            )
            i += 1
    if i:
        url = f'https://api.partner.market.yandex.ru/v2/campaigns/{campaign_id}/offer-prices/updates.json'
        data = {
            'offers': batch
        }
        trys = 0
        res = None
        while True:
            if trys >= TRY:
                break
            try:
                res = requests.post(url, headers=headers, json=data)
            except Exception as e:
                logging.warning(str(e))
                pass
            else:
                if res:
                    logging.info(res.text)
                    for batch_elem in batch:
                        final.add(batch_elem['id'])
                    break
            trys += 1
            logging.warning(f"Error offer-prices/updates.json request. Sleep for {YANDEX_API_PAUSE}")

    return final


def set_stocks(headers, campaign_id, prices: dict, batch_size: int, warehouse_id: int):
    """
    :param prices: utm_term: str (yandex_id: str) -> (sku: str, mpn: str or None, price: str, price_old: str, price_wholesale: str, quantity: int)
    """
    date_update = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S+03:00")
    batch = []
    i = 0
    for id in prices:
        if i and i % batch_size == 0:
            url = f'https://api.partner.market.yandex.ru/v2/campaigns/{campaign_id}/offers/stocks.json'
            data = {
                'skus': batch
            }
            trys = 0
            res = None
            while True:
                if trys >= TRY:
                    break
                try:
                    res = requests.put(url, headers=headers, json=data)
                except Exception as e:
                    logging.warning(str(e))
                    pass
                else:
                    if res:
                        logging.info(res.text)
                        break
                    else:
                        logging.warning(res.text)
                trys += 1
                logging.warning(f"Error offers/stocks.json request. Sleep for {YANDEX_API_PAUSE}")
                time.sleep(YANDEX_API_PAUSE)
            batch = []
            i = 0

        else:
            try:
                stock = int(prices[id][5])
            except:
                stock = 0
            batch.append(
                {
                    'sku': id,
                    'warehouseId': warehouse_id,
                    'items': [
                        {
                            'type': "FIT",
                            'count': stock,
                            'updatedAt': date_update,
                        }
                    ]
                }
            )
            i += 1


def get_products_report(headers, campaign_id):
    url = f'https://api.partner.market.yandex.ru/v2/campaigns/{campaign_id}/stats/skus.json'
    data = {
        'shopSkus': ['719426']
    }
    res = requests.post(url, headers=headers, json=data)
    print(res.text)


def get_offers(headers, campaign_id): #TODO долго работаает, около 40к товаров
    base_url = f'https://api.partner.market.yandex.ru/v2/campaigns/{campaign_id}/offer-mapping-entries.json'
    url = base_url
    # res = []
    res2 = dict()
    stop_flag = False

    while True:
        try:
            resp = requests.get(url, headers=headers)
            res_dict = json.loads(resp.text)['result']
        except:
            break

        next_page = None
        if 'paging' in res_dict:
            next_page = res_dict['paging'].get('nextPageToken')

        if res_dict.get('offerMappingEntries'):
            for elem in res_dict['offerMappingEntries']:
                if 'offer' in elem and 'mapping' in elem:
                    res_elem = dict()
                    res_elem['shopSku'] = elem['offer'].get('shopSku')
                    res_elem['vendorCode'] = elem['offer'].get('vendorCode')
                    res_elem['marketSku'] = elem['mapping'].get('marketSku')
                    # res.append(res_elem)
                    if res_elem['shopSku'] in res2:
                        stop_flag = True
                        break
                    res2[res_elem['shopSku']] = res_elem

        if next_page:
            url = base_url + f'?page_token={next_page}'
        else:
            break

        if stop_flag:
            break

    return res2
    # print(len(res2))


def get_orders(headers, campaign_id, delta_days):
    base_url = f'https://api.partner.market.yandex.ru/campaigns/{campaign_id}/orders'
    dt = datetime.datetime.now() - datetime.timedelta(days=delta_days)
    date_since = dt.strftime(YANDEX_DATE_FORMAT)
    date_to = datetime.datetime.now().strftime(YANDEX_DATE_FORMAT)
    params = {
        'fromDate': date_since,
        # 'toDate': date_to,
        # 'status': 'PROCESSING'

    }
    resp = requests_get_params(base_url, params=params, headers=headers)
    # print(resp.text)
    try:
        orders = json.loads(resp.text)['orders']
    except Exception as e:
        logging.warning(str(e))
        orders = []
    return orders


def get_order_label(headers, campaign_id, order_id, file_path):
    base_url = f'https://api.partner.market.yandex.ru/campaigns/{campaign_id}/orders/{order_id}/delivery/labels'
    # resp = requests_get_params(base_url, params={'format': 'A7'}, headers=headers)
    resp = requests_get(base_url, headers=headers)
    if resp.ok:
        res_content = resp.content
        with open(file_path, 'wb') as outfile:
            outfile.write(res_content)
    # else:
    #     print(resp.text)
    return resp.ok


def get_order(headers, campaign_id, order_id):
    base_url = f'https://api.partner.market.yandex.ru/campaigns/{campaign_id}/orders/{order_id}'
    # resp = requests_get_params(base_url, params={'format': 'A7'}, headers=headers)
    resp = requests_get(base_url, headers=headers)
    print(resp.text)
    return resp.text


def change_order_status(headers, campaign_id, order_id, status, substatus=None):
    base_url = f'https://api.partner.market.yandex.ru/campaigns/{campaign_id}/orders/{order_id}/status'
    data = {
        "order": {
            "status": status,
        }
    }
    if substatus:
        data['order']["substatus"] = substatus
    try:
        resp = requests.put(base_url, headers=headers, json=data)
    except Exception as e:
        logging.warning(str(e))
        return False
    if not resp.ok:
        logging.warning(resp.text)
    return resp.ok


def get_orders_v2(headers, campaign_id, delta_days):
    base_url = f'https://api.partner.market.yandex.ru/campaigns/{campaign_id}/orders'
    dt = datetime.datetime.now() - datetime.timedelta(days=delta_days)
    date_since = dt.strftime(YANDEX_DATE_FORMAT)
    page = 1
    res = []

    while True:
        params = {
            'fromDate': date_since,
            "page": page
        }

        resp = requests_get_params(base_url, params=params, headers=headers)
        # print(resp.text)
        try:
            res_dict = json.loads(resp.text)
            orders = res_dict['orders']
        except Exception as e:
            logging.warning(str(e))
            break

        res.extend(orders)

        if res_dict.get('pager', {}).get('pagesCount', 1) == page:
            break

        page += 1

    return res


def get_returned(headers, campaign_id, delta_days):
    base_url = f'https://api.partner.market.yandex.ru/campaigns/{campaign_id}/returns'
    dt = datetime.datetime.now() - datetime.timedelta(days=delta_days)
    date_since = dt.strftime(YANDEX_DATE_FORMAT)
    page_token = None
    res = []

    while True:
        params = {
            'fromDate': date_since,
            "page_token": page_token
        }

        resp = requests_get_params(base_url, params=params, headers=headers)
        # print(resp.text)
        try:
            res_dict = json.loads(resp.text)
            res_dict = res_dict['result']
        except Exception as e:
            logging.warning(str(e))
            break

        res.extend(res_dict.get('returns', []))

        page_token = res_dict.get('paging', {}).get('nextPageToken')
        if not page_token:
            break

    return res


def get_fby_orders(headers, campaign_id, delta_days):
    base_url = f'https://api.partner.market.yandex.ru/v2/campaigns/{campaign_id}/stats/orders'
    url = base_url
    res = []
    stop_flag = False

    dt = datetime.datetime.now() - datetime.timedelta(days=delta_days)
    date_since = dt.strftime(YANDEX_DATE_FORMAT)
    body = {
        'dateFrom': date_since
    }

    while True:
        try:
            resp = requests.post(url, headers=headers, json=body)
            res_dict = json.loads(resp.text)['result']
        except:
            break

        next_page = None
        if 'paging' in res_dict:
            next_page = res_dict['paging'].get('nextPageToken')

        res.extend(res_dict.get('orders', []))

        if next_page:
            url = base_url + f'?page_token={next_page}'
        else:
            break

        if stop_flag:
            break

    return res


def get_all_products(headers, businessId, limit=None):
    url = f'https://api.partner.market.yandex.ru/businesses/{businessId}/offer-mappings'
    params = {
        'limit': 200
    }
    res = []

    while True:
        time.sleep(1)
        resp = requests.post(url, headers=headers, params=params)
        # print(resp.text)
        try:
            res_dict = json.loads(resp.text)['result']
        except Exception as e:
            logging.warning(str(e))
            logging.warning(resp.text)
            break

        next_page = None
        if 'paging' in res_dict:
            next_page = res_dict['paging'].get('nextPageToken')
            # print(next_page)

        res.extend(res_dict.get('offerMappings', []))
        # print(len(res_dict.get('offerMappings', [])), len(res))
        # print(res_dict.get('offerMappings', [])[0])

        if next_page:
            params['page_token'] = next_page
        else:
            break

        if limit and len(res) >= limit:
            break

    return res


def get_calculates(headers, offers, campaignId, sellingProgram="FBS", frequency="DAILY"):
    """
    "offers": [
        {
            "categoryId": 0,
            "price": 0,
            "length": 0,
            "width": 0,
            "height": 0,
            "weight": 0,
            "quantity": 1
        }
    ]
    """
    url = f'https://api.partner.market.yandex.ru/tariffs/calculate'
    limit = 200
    res = []

    for i in range(0, len(offers), limit):
        start_index = i
        end_index = i + limit
        if end_index > len(offers):
            end_index = len(offers)
        offers_batch = offers[start_index: end_index]
        data = {
            "parameters": {
                "campaignId": campaignId,
                # "sellingProgram": sellingProgram, # Указываем либо campaignId либо sellingProgram
                "frequency": frequency
            },
            "offers": offers_batch
        }
        # print(data)
        time.sleep(1)
        resp = requests.post(url, headers=headers, json=data)
        # print(resp.text)
        try:
            res_list = json.loads(resp.text)['result']['offers']
        except Exception as e:
            logging.warning(str(e))
            logging.warning(resp.text)
            continue

        res.extend(res_list)

    return res


def get_campaigns(headers):
    base_url = f'https://api.partner.market.yandex.ru/campaigns'
    # resp = requests_get_params(base_url, params={'format': 'A7'}, headers=headers)
    resp = requests_get(base_url, headers=headers)
    try:
        res_list = json.loads(resp.text)['campaigns']
    except Exception as e:
        logging.warning(str(e))
        logging.warning(resp.text)
        return []
    return res_list


def get_orders_report_un(headers, campaign_id, date_from, date_to=None):
    """
    Формат даты: ГГГГ‑ММ‑ДД.
    """
    base_url = f'https://api.partner.market.yandex.ru/v2/campaigns/{campaign_id}/stats/orders'
    url = base_url
    res = []
    stop_flag = False

    body = {
        'dateFrom': date_from
    }
    if date_to:
        body['dateTo'] = date_to

    while True:
        try:
            resp = requests_post(url, headers=headers, data=body)
            # logging.info(resp.text)
            res_dict = json.loads(resp.text)['result']
        except:
            break

        next_page = None
        if 'paging' in res_dict:
            next_page = res_dict['paging'].get('nextPageToken')

        res.extend(res_dict.get('orders', []))

        if next_page:
            url = base_url + f'?page_token={next_page}'
        else:
            break

        if stop_flag:
            break

    final_res = []
    for elem in res:
        # logging.info(elem)
        if elem.get('commissions'):
            for commission_dict in elem['commissions']:
                elem['COMISSION_' + commission_dict['type']] = commission_dict['actual']
        if elem.get('subsidies'):
            for subsidie_dict in elem['subsidies']:
                elem[subsidie_dict['type'] + '_' + subsidie_dict['operationType']] = subsidie_dict['amount']
        if elem.get('payments'):
            for payment_dict in elem['payments']:
                key = payment_dict['type'] + '_' + payment_dict['source']
                if key not in elem:
                    elem[key] = 0
                elem[key] += payment_dict['total']
        for item in elem.get('items', []):
            elem_copy = elem.copy()
            elem_copy['offerName'] = item.get('offerName')
            elem_copy['marketSku'] = item.get('marketSku')
            elem_copy['shopSku'] = item.get('shopSku')
            elem_copy['count'] = item.get('count')
            if item.get('prices'):
                for price_dict in item['prices']:
                    elem_copy['PRICE_'+price_dict['type']] = price_dict['total']
            final_res.append(elem_copy)

    return final_res


def get_orders_un(headers, campaign_id, date_from, date_to=None):
    base_url = f'https://api.partner.market.yandex.ru/campaigns/{campaign_id}/orders'
    page = 1
    res = []

    while True:
        params = {
            'fromDate': date_from,
            "page": page
        }
        if date_to:
            params['toDate'] = date_to

        resp = requests_get_params(base_url, params=params, headers=headers)
        # print(resp.text)
        try:
            res_dict = json.loads(resp.text)
            orders = res_dict['orders']
        except Exception as e:
            logging.warning(str(e))
            break

        res.extend(orders)

        if res_dict.get('pager', {}).get('pagesCount', 1) == page:
            break

        page += 1

    final_res = []
    for elem in res:
        # logging.info(elem)
        if elem.get('shipments'):
            elem['shipments'] = json.dumps(elem['shipments'])
        if elem.get('notes'):
            elem['notes'] = elem['notes'][:255]
        if elem.get('subsidies'):
            for subsidie_dict in elem['subsidies']:
                elem['order_subsidy_' + subsidie_dict['type']] = subsidie_dict['amount']
        for item in elem.get('items', []):
            elem_copy = elem.copy()
            for key in item:
                if key == 'prices':
                    for price_dict in item['prices']:
                        elem_copy['item_price_' + price_dict['type']] = price_dict['total']
                elif key == 'subsidies':
                    for price_dict in item['subsidies']:
                        elem_copy['item_subsidy_'+price_dict['type']] = price_dict['amount']
                elif key == 'promos':
                    for price_dict in item['promos']:
                        elem_copy['item_promo_'+price_dict['type']] = price_dict['subsidy']
                else:
                    elem_copy['item_'+key] = item.get(key)
            final_res.append(elem_copy)

    return final_res


def get_returns_un(headers, campaign_id, date_from, date_to=None):
    base_url = f'https://api.partner.market.yandex.ru/campaigns/{campaign_id}/returns'
    page_token = None
    res = []

    while True:
        params = {
            'fromDate': date_from,
        }
        if date_to:
            params['toDate'] = date_to
        if page_token:
            params['page_token'] = page_token

        resp = requests_get_params(base_url, params=params, headers=headers)
        try:
            res_dict = json.loads(resp.text)
            res_dict = res_dict['result']
        except Exception as e:
            logging.warning(str(e))
            break

        res.extend(res_dict.get('returns', []))

        page_token = res_dict.get('paging', {}).get('nextPageToken')
        if not page_token:
            break

    final_res = []
    for elem in res:
        # logging.info(elem)
        if elem.get('logisticPickupPoint') and elem.get('logisticPickupPoint', {}).get('address'):
            elem['address'] = elem['logisticPickupPoint']['address']
        for item in elem.get('items', []):
            elem_copy = elem.copy()
            for key in item:
                if key == 'instances' and item['instances']:
                    elem_copy['item_status'] = item['instances'][0].get('status')
                elif key == 'tracks' and item['tracks']:
                    elem_copy['item_trackCode'] = item['tracks'][0].get('trackCode')
                elif key == 'decisions' and item['decisions']:
                    elem_copy['item_comment'] = item['decisions'][0].get('comment')
                else:
                    elem_copy['item_' + key] = item.get(key)
            final_res.append(elem_copy)

    return final_res


def get_offers_un(headers, campaign_id, date_from, date_to=None):
    base_url = f'https://api.partner.market.yandex.ru/campaigns/{campaign_id}/offers'
    page_token = None
    res = []

    while True:
        params = {}
        if page_token:
            params['page_token'] = page_token
        resp = requests.post(base_url, headers=headers, json={}, params=params)
        try:
            res_dict = json.loads(resp.text)
            res_dict = res_dict['result']
        except Exception as e:
            logging.warning(str(e))
            break

        res.extend(res_dict.get('offers', []))
        page_token = res_dict.get('paging', {}).get('nextPageToken')
        if not page_token:
            break

    for elem in res:
        # logging.info(elem)
        if elem.get('errors'):
            elem['errors'] = ', '.join([i['comment'] for i in elem['errors']])
        if elem.get('warnings'):
            elem['warnings'] = ', '.join([i['message'] for i in elem['warnings']])

    return res


def get_stocks_un(headers, campaign_id, date_from, date_to=None):
    base_url = f'https://api.partner.market.yandex.ru/campaigns/{campaign_id}/offers/stocks'
    page_token = None
    res = []

    while True:
        params = {}
        if page_token:
            params['page_token'] = page_token
        resp = requests.post(base_url, headers=headers, json={}, params=params)
        # print(resp.text)
        try:
            res_dict = json.loads(resp.text)
            res_dict = res_dict['result']
        except Exception as e:
            logging.warning(str(e))
            break

        res.extend(res_dict.get('warehouses', []))
        page_token = res_dict.get('paging', {}).get('nextPageToken')
        if not page_token:
            break

    offers_dict = dict()
    for elem in res:
        # logging.info(elem)
        warehouse_id = elem.get('warehouseId')
        if not warehouse_id:
            logging.warning(f"No warehouseId in{elem}")
            continue
        for offer in elem.get('offers', []):
            offer_id = offer.get('offerId')
            if not offer_id:
                logging.warning(f"No offerId in {offer}")
                continue
            if offer_id not in offers_dict:
                offers_dict[offer_id] = {}
            if warehouse_id not in offers_dict[offer_id]:
                offers_dict[offer_id][warehouse_id] = {}
            updated_at = offer.get('updatedAt', '')
            for stock in offer.get('stocks', []):
                type = stock.get('type')
                if not type:
                    continue
                if type not in offers_dict[offer_id][warehouse_id]:
                    offers_dict[offer_id][warehouse_id][type] =[0, '']
                offers_dict[offer_id][warehouse_id][type][0] += stock.get('count', 0)
                offers_dict[offer_id][warehouse_id][type][1] = updated_at

    final_res = []
    for offer_id in offers_dict:
        for warehouse_id in offers_dict[offer_id]:
            offer_elem = {
                'offer_id': offer_id,
                'warehouse_id': warehouse_id
            }
            for type in offers_dict[offer_id][warehouse_id]:
                offer_elem['updated_at'] = offers_dict[offer_id][warehouse_id][type][1]
                offer_elem['stock_'+type] = offers_dict[offer_id][warehouse_id][type][0]
            final_res.append(offer_elem)

    return final_res


def get_prices_un(headers, campaign_id, date_from, date_to=None):
    """
    Цены конкретного магазина/кампании ("В магазине") - фактическая цена, за которую
    товар отображается на витрине именно этого магазина (FBY/DBS и т.п. могут отличаться).
    """
    base_url = f'https://api.partner.market.yandex.ru/campaigns/{campaign_id}/offer-prices'
    page_token = None
    res = []

    while True:
        params = {}
        if page_token:
            params['page_token'] = page_token
        resp = requests.post(base_url, headers=headers, json={}, params=params)
        try:
            res_dict = json.loads(resp.text)
            res_dict = res_dict['result']
        except Exception as e:
            logging.warning(str(e))
            break

        res.extend(res_dict.get('offers', []))
        page_token = res_dict.get('paging', {}).get('nextPageToken')
        if not page_token:
            break

    return res


def get_default_prices_un(headers, business_id, date_from=None, date_to=None):
    """
    Цены "по умолчанию" на уровне кабинета ("В кабинете") - единая цена продавца по всем
    магазинам бизнес-аккаунта ("цена из ЛК"), в отличие от get_prices_un (цена конкретного магазина).
    """
    base_url = f'https://api.partner.market.yandex.ru/v2/businesses/{business_id}/offer-prices'
    page_token = None
    res = []

    while True:
        params = {}
        if page_token:
            params['page_token'] = page_token
        resp = requests.post(base_url, headers=headers, json={}, params=params)
        try:
            res_dict = json.loads(resp.text)
            res_dict = res_dict['result']
        except Exception as e:
            logging.warning(str(e))
            break

        res.extend(res_dict.get('offers', []))
        page_token = res_dict.get('paging', {}).get('nextPageToken')
        if not page_token:
            break

    return res


def get_mappings_un(headers, business_id, date_from=None, date_to=None):
    url = f'https://api.partner.market.yandex.ru/businesses/{business_id}/offer-mappings'
    params = {
        'limit': 200
    }
    res = []

    while True:
        time.sleep(1)
        resp = requests.post(url, headers=headers, params=params)
        # print(resp.text)
        try:
            res_dict = json.loads(resp.text)['result']
        except Exception as e:
            logging.warning(str(e))
            logging.warning(resp.text)
            break

        next_page = None
        if 'paging' in res_dict:
            next_page = res_dict['paging'].get('nextPageToken')
            # print(next_page)

        res.extend(res_dict.get('offerMappings', []))
        # print(len(res_dict.get('offerMappings', [])), len(res))
        # print(res_dict.get('offerMappings', [])[0])

        if next_page:
            params['page_token'] = next_page
        else:
            break

    final_res = []
    for elem in res:
        offer = elem.get('offer', {})
        mapping = elem.get('mapping', {})
        elem_dict = {
            'offerId': offer.get('offerId'),
            'name': offer.get('name'),
            'category': offer.get('category'),
            'vendor': offer.get('vendor'),
            'barcodes': ','.join(offer.get('barcodes', [])),
            'manufacturerCountries': ','.join(offer.get('manufacturerCountries', [])),
            'dimensions': offer.get('weightDimensions'),
            'vendorCode': offer.get('vendorCode'),
            'cardStatus': offer.get('cardStatus'),
            'archived': offer.get('archived'),
            'marketSku': mapping.get('marketSku', 0),
            'marketSkuName': mapping.get('marketSkuName'),
            'marketModelId': mapping.get('marketModelId', 0),
            'marketModelName': mapping.get('marketModelName'),
            'marketCategoryId': mapping.get('marketCategoryId', 0),
            'marketCategoryName': mapping.get('marketCategoryName'),
        }
        if offer.get('basicPrice'):
            elem_dict['basicPrice'] = offer['basicPrice']
        if offer.get('shelfLife'):
            elem_dict['shelfLife'] = offer['shelfLife']

        for sellingProgram in offer.get('sellingPrograms', []):
            elem_dict[sellingProgram.get('sellingProgram')] = sellingProgram.get('status')
        final_res.append(elem_dict)

    return final_res


def get_promos(headers, business_id):
    url = f'https://api.partner.market.yandex.ru/businesses/{business_id}/promos'
    resp = requests.post(url, headers=headers)
    try:
        res_dict = json.loads(resp.text)['result']['promos']
    except Exception as e:
        logging.warning(str(e))
        logging.warning(resp.text)
        return []
    return res_dict


def get_promos_un(headers, business_id, date_from=None, date_to=None):
    promos = get_promos(headers,business_id)
    promos_ids = [elem.get('id') for elem in promos]
    url = f'https://api.partner.market.yandex.ru/businesses/{business_id}/promos/offers'
    final_res = []
    for promo_id in promos_ids:
        params = {
            'limit': 500
        }
        body = {
            'promoId': promo_id
        }
        res = []

        while True:
            resp = requests.post(url, headers=headers, params=params, json=body)
            try:
                res_dict = json.loads(resp.text)['result']
            except Exception as e:
                logging.warning(str(e))
                logging.warning(resp.text)
                break

            next_page = None
            if 'paging' in res_dict:
                next_page = res_dict['paging'].get('nextPageToken')
                # print(next_page)

            res.extend(res_dict.get('offers', []))
            # print(len(res_dict.get('offerMappings', [])), len(res))
            # print(res_dict.get('offerMappings', [])[0])

            if next_page:
                params['page_token'] = next_page
            else:
                break
        for elem in res:
            elem['promo_id'] = promo_id
            final_res.append(elem)

    return final_res


def order_orders_report(headers, business_id, date_from, date_to):
    url = f'https://api.partner.market.yandex.ru/reports/united-orders/generate'
    body = {
        'businessId': business_id,
        'dateFrom': date_from,
        'dateTo': date_to,
        # 'campaignIds': campaign_ids,
    }
    resp = requests.post(url, headers=headers, json=body)
    try:
        res_dict = json.loads(resp.text)['result']
    except Exception as e:
        logging.warning(str(e))
        logging.warning(resp.text)
        return {}
    return res_dict


def get_allorders_report(headers, business_id, date_from, date_to):
    report_id = None
    wait_time = 0
    for _ in range(TRY):
        order_dict = order_orders_report(headers, business_id, date_from, date_to)
        if order_dict and order_dict.get('reportId'):
            report_id = order_dict['reportId']
            wait_time = order_dict.get('estimatedGenerationTime', 0)
            break
        logging.warning(f"get_allorders_report_un, order_dict: {order_dict}")
        time.sleep(SLEEP_TIME)
    if not report_id:
        return []

    pause = wait_time/1000 + SLEEP_TIME
    logging.info(f"Wait for {pause}sec for {report_id} report...")
    time.sleep(pause)
    file_url = None
    url = f'https://api.partner.market.yandex.ru/reports/info/{report_id}'
    for _ in range(TRY):
        resp = requests.get(url, headers=headers)
        try:
            res_dict = json.loads(resp.text)
        except Exception as e:
            logging.warning(f"get_allorders_report_un, json.loads(resp.text): {str(e)}")
            time.sleep(SLEEP_TIME)
            continue
        status = res_dict.get('result', {}).get('status', '')
        if status == 'DONE':
            file_url = res_dict['result'].get('file')
            break
        time.sleep(SLEEP_TIME * 3)

    return file_url

def order_marketplace_services_report(headers, business_id, date_from, date_to):
    url = f'https://api.partner.market.yandex.ru/reports/united-marketplace-services/generate'
    body = {
        'businessId': business_id,
        'dateFrom': date_from,
        'dateTo': date_to,
    }
    param = {
        'format': 'FILE'
    }
    resp = requests.post(url, headers=headers, json=body, params=param)
    try:
        res_dict = json.loads(resp.text)['result']
    except Exception as e:
        logging.warning(str(e))
        logging.warning(resp.text)
        return {}
    return res_dict

def get_marketplace_services_report(headers, business_id, date_from, date_to):
    report_id = None
    wait_time = 0
    for _ in range(TRY):
        order_dict = order_marketplace_services_report(headers, business_id, date_from, date_to)
        if order_dict and order_dict.get('reportId'):
            report_id = order_dict['reportId']
            wait_time = order_dict.get('estimatedGenerationTime', 0)
            break
        logging.warning(f"get_marketplace_services_report, order_dict: {order_dict}")
        time.sleep(130)  # rate limit: 1 запрос в 2 минуты
    if not report_id:
        return None

    pause = wait_time / 1000 + SLEEP_TIME
    logging.info(f"Wait for {pause}sec for {report_id} report...")
    time.sleep(pause)
    file_url = None
    url = f'https://api.partner.market.yandex.ru/reports/info/{report_id}'
    for _ in range(TRY):
        resp = requests.get(url, headers=headers)
        try:
            res_dict = json.loads(resp.text)
        except Exception as e:
            logging.warning(f"get_marketplace_services_report, json.loads: {str(e)}")
            time.sleep(SLEEP_TIME)
            continue
        status = res_dict.get('result', {}).get('status', '')
        if status == 'DONE':
            file_url = res_dict['result'].get('file')
            break
        time.sleep(SLEEP_TIME * 3)

    return file_url


BOOST_RATE_LIMIT_SEC = 121  # лимит ЯМ с 18.05.2026: 1 генерация /reports/boost-consolidated в 2 минуты
_last_boost_order_ts = 0.0


def order_boost_report(headers, business_id, date_from, date_to):
    global _last_boost_order_ts
    wait = BOOST_RATE_LIMIT_SEC - (time.time() - _last_boost_order_ts)
    if wait > 0:
        logging.info(f"Boost rate limit: wait {round(wait)}sec before ordering report...")
        time.sleep(wait)
    url = f'https://api.partner.market.yandex.ru/reports/boost-consolidated/generate'
    body = {
        'businessId': business_id,
        'dateFrom': date_from,
        'dateTo': date_to,
        # 'campaignIds': campaign_ids,
    }
    param = {
        'format': 'JSON'
    }
    resp = requests.post(url, headers=headers, json=body, params=param)
    _last_boost_order_ts = time.time()
    try:
        res_dict = json.loads(resp.text)['result']
    except Exception as e:
        logging.warning(str(e))
        logging.warning(resp.text)
        return {}
    return res_dict


def get_boost_report(headers, business_id, date_from, date_to):
    report_id = None
    wait_time = 0
    for _ in range(TRY):
        order_dict = order_boost_report(headers, business_id, date_from, date_to)
        if order_dict and order_dict.get('reportId'):
            report_id = order_dict['reportId']
            wait_time = order_dict.get('estimatedGenerationTime', 0)
            break
        logging.warning(f"get_boost_report, order_dict: {order_dict}")
        time.sleep(SLEEP_TIME)
    if not report_id:
        return []

    pause = wait_time/1000 + SLEEP_TIME
    logging.info(f"Wait for {pause}sec for {report_id} report...")
    time.sleep(pause)
    file_url = None
    url = f'https://api.partner.market.yandex.ru/reports/info/{report_id}'
    for _ in range(TRY):
        resp = requests.get(url, headers=headers)
        try:
            res_dict = json.loads(resp.text)
        except Exception as e:
            logging.warning(f"get_boost_report, json.loads(resp.text): {str(e)}")
            time.sleep(SLEEP_TIME)
            continue
        status = res_dict.get('result', {}).get('status', '')
        if status == 'DONE':
            file_url = res_dict['result'].get('file')
            break
        time.sleep(SLEEP_TIME * 3)

    return file_url


def order_shelf_report(headers, business_id, date_from, date_to, type='CLICKS'):
    url = f'https://api.partner.market.yandex.ru/reports/shelf-statistics/generate'
    body = {
        'businessId': business_id,
        'dateFrom': date_from,
        'dateTo': date_to,
        'attributionType': type,
    }
    param = {
        'format': 'JSON'
    }
    resp = requests.post(url, headers=headers, json=body, params=param)
    try:
        res_dict = json.loads(resp.text)['result']
    except Exception as e:
        logging.warning(str(e))
        logging.warning(resp.text)
        return {}
    return res_dict


def get_shelf_report(headers, business_id, date_from, date_to, type='CLICKS'):
    report_id = None
    wait_time = 0
    for _ in range(TRY):
        order_dict = order_shelf_report(headers, business_id, date_from, date_to, type=type)
        if order_dict and order_dict.get('reportId'):
            report_id = order_dict['reportId']
            wait_time = order_dict.get('estimatedGenerationTime', 0)
            break
        logging.warning(f"get_boost_report, order_dict: {order_dict}")
        time.sleep(SLEEP_TIME)
    if not report_id:
        return []

    pause = wait_time/1000 + SLEEP_TIME
    logging.info(f"Wait for {pause}sec for {report_id} report...")
    time.sleep(pause)
    file_url = None
    url = f'https://api.partner.market.yandex.ru/reports/info/{report_id}'
    for _ in range(TRY):
        resp = requests.get(url, headers=headers)
        try:
            res_dict = json.loads(resp.text)
        except Exception as e:
            logging.warning(f"get_boost_report, json.loads(resp.text): {str(e)}")
            time.sleep(SLEEP_TIME)
            continue
        status = res_dict.get('result', {}).get('status', '')
        if status == 'DONE':
            file_url = res_dict['result'].get('file')
            break
        time.sleep(SLEEP_TIME * 3)

    return file_url
