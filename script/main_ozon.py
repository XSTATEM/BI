# -- coding: utf-8 --
"""
Автор: Олег Шабалов
Контакты: 89179021656, @olegshabalov

Выгрузка данных из Ozon в базу
"""

import datetime
import logging
import sys
import os

from db import Database
import ozon
import ozon_perfomance
import lib
from telegram_bot.notifier import notify_success, notify_error

from settings import DIR_DATA, ACCOUNTS_XLSX_FILE, PSQL_DATABASE, PSQL_USER, PSQL_PASW, PSQL_HOST, \
    PSQL_PORT, WB_DATE_FORMAT, WB_DATETIME_FORMAT, MAX_STR_SIZE

####################################################### ENTITIES #######################################################
ENTITIES = [
    {
        'type': 'ozon',
        'table': 'ozon_finance_realization',
        'index_fields': ['start_date', 'rowNumber', 'client_id'],
        'func': ozon.get_finance_realization_un_v2,
        'period': 7 * 24,  # hours 14*24
        'init_period': 90 * 24,  # only one month allowed?
        'skip_fields': None,
        'que': ['2']
    },
    {
        'type': 'ozon',
        'table': 'ozon_finance_transaction',
        'index_fields': ['operation_id', 'client_id'],
        'func': ozon.get_transactions_moments_un, #в случае большого кол-хва данных использовать get_transactions_moments_un_v2
        'period': 4 * 24, #14 hours 14*24
        'init_period': 30 * 24, #only one month allowed
        'skip_fields': [],
        'limit_list_fields': ['items'],
        'que': ['2']
    },
    # {
    #     'type': 'ozon',
    #     'table': 'ozon_finance_transaction',
    #     'index_fields': ['operation_id', 'client_id'],
    #     'func': ozon.get_transactions_moments_un_v2,
    #     # в случае большого кол-хва данных использовать get_transactions_moments_un_v2
    #     'period': 36,  # 14 hours 14*24
    #     'init_period': 30 * 24,  # only one month allowed
    #     'skip_fields': [],
    #     'limit_list_fields': ['items'],
    #     'que': ['3']
    # },
    {
        'type': 'ozon',
        'table': 'ozon_daily_stocks',
        'index_fields': ['item_code', 'warehouse_name', 'client_id', 'date'],
        'cache_key': 'stocks',
        'func': ozon.get_daily_stocks_report_un,
        'period': 14 * 24,  # hours 14*24
        'init_period': 90 * 24,
        'skip_fields': None,
        'que': ['1']
    },
    {
        'type': 'ozon',
        'table': 'ozon_stocks',
        'index_fields': ['item_code', 'warehouse_name', 'client_id'],
        'cache_key': 'stocks', # Только после ozon_daily_stocks!!!
        'func': ozon.get_stocks_report_un,
        'period': 14 * 24,  # hours 14*24
        'init_period': 90 * 24,
        'skip_fields': None,
        'que': ['1']
    },
    {
        'type': 'ozon',
        'table': 'ozon_products_report',
        'index_fields': ['ozon_product_id', 'client_id'],
        'func': ozon.get_products_report_un,
        'period': 14 * 24,  # hours 14*24
        'init_period': 90 * 24,
        'skip_fields': None,
        'que': ['2'],
        'preset_fields_types_dict': {'preduprezhdenija': f'TEXT', 'oshibki': f'TEXT'} # field preduprezhdenija, oshibki -> TEXT
    },
    # {
    #     'type': 'ozon',
    #     'table': 'ozon_fbo_orders',
    #     'index_fields': ['posting_number', 'client_id'],
    #     'func': ozon.get_fbo_orders_un,
    #     'period': 14 * 24,  # hours 14*24
    #     'init_period': 90 * 24,
    #     'skip_fields': None  # list
    # },
    {
        'type': 'ozon',
        'table': 'ozon_fbo_orders2',
        'index_fields': ['posting_number', 'offer_id', 'client_id'],
        'func': ozon.get_fbo_orders_v2_un,
        'period': 10 * 24,  # hours 14*24
        'init_period': 90 * 24,
        'skip_fields': ['products', 'item_services'],
        'que': ['1', '3']
    },
    # {
    #     'type': 'ozon',
    #     'table': 'ozon_fbs_orders',
    #     'index_fields': ['posting_number', 'client_id'],
    #     'func': ozon.get_fbs_orders_un,
    #     'period': 14 * 24,  # hours 14*24
    #     'init_period': 90 * 24,
    #     'skip_fields': None  # list
    # },
    {
        'type': 'ozon',
        'table': 'ozon_fbs_orders2',
        'index_fields': ['posting_number', 'offer_id', 'client_id'],
        'func': ozon.get_fbs_orders_v2_un,
        'period': 10 * 24,  # hours 14*24
        'init_period': 90 * 24,
        'skip_fields': ['products'],
        'que': ['1', '3']
    },
    {
        'type': 'ozon_perfomance',
        'table': 'ozon_perfomance_statistics',
        'index_fields': ['id', 'date', 'client_id'],
        'func': ozon_perfomance.get_perfomance_stat_un,
        'period': 14 * 24,  # hours 14*24
        'init_period': 60 * 24, #"error":"max statistics period: 62 days"
        'skip_fields': None,
        'que': ['2']
    },
    # {
    #     'type': 'ozon_perfomance',
    #     'table': 'ozon_campaign_sku',
    #     'index_fields': ['campaign_id', 'sku', 'client_id'],
    #     'func': ozon_perfomance.get_campaign_skus,
    #     'period': 7 * 24,  # hours 14*24
    #     'init_period': 90 * 24,
    #     'skip_fields': None,
    #     'que': ['2']
    # },  # отключено: campaign/{id}/objects бьёт по каждой кампании и почти всегда ошибается
    # на старых/архивных кампаниях (десятки минут впустую), рекламу грузим через куки отдельно
    {
        'type': 'ozon',
        'table': 'ozon_analytics',
        'index_fields': ['sku', 'day', 'client_id'],
        'func': ozon.get_analitics_data_un,
        'period': 7 * 24,  # 7
        'init_period': 90 * 24,
        'skip_fields': None,
        'que': ['2']
    },
    {
        'type': 'ozon',
        'table': 'ozon_fbo_orders_report',
        'index_fields': ['nomer_otpravlenija', 'client_id'],
        'func': ozon.get_fbo_orders_report_un,
        'period': 7 * 24,  # 7 #TODO
        'init_period': 90 * 24,
        'skip_fields': None,
        'que': ['2']
    },
    {
        'type': 'ozon',
        'table': 'ozon_fbs_orders_report',
        'index_fields': ['nomer_otpravlenija', 'client_id'],
        'func': ozon.get_fbs_orders_report_un,
        'period': 7 * 24,  # 7 #TODO
        'init_period': 90 * 24,
        'skip_fields': None,
        'que': ['2'],
        'preset_fields_types_dict': {'data_otmeny': f'VARCHAR({MAX_STR_SIZE})', 'data_otgruzki_bez_prosrochki': f'VARCHAR({MAX_STR_SIZE})'} #Необходимо в базе данных сенить типа полей data_otmeny и data_otgruzki_bez_prosrochki на varchar(255)
    },
    {
        'type': 'ozon',
        'table': 'ozon_categories',
        'index_fields': ['offer_id', 'client_id'],
        'func': ozon.get_categories_v2_un,
        'period': 7 * 24,  # не используется
        'init_period': 90 * 24, # не используется
        'skip_fields': None,
        'que': ['2']
    },
    {
        'type': 'ozon',
        'table': 'ozon_stocks_analytic',
        'index_fields': ['offer_id', 'client_id'],
        'func': ozon.get_stocks_analytic_un,
        'period': 7 * 24,  # не используется
        'init_period': 90 * 24,  # не используется
        'skip_fields': None,
        'que': ['2'],
        'preset_fields_types_dict': {'ads': f'VARCHAR({MAX_STR_SIZE})', 'ads_cluster': f'VARCHAR({MAX_STR_SIZE})'} #ads, ads_cluster-> varchar - invalid input syntax for type bigint: ""
    },
    {
        'type': 'ozon',
        'table': 'ozon_daily_prices',  # историчный срез цен - одна строка на offer_id в день
        'index_fields': ['offer_id', 'client_id', 'date'],
        'cache_key': 'prices',
        'func': ozon.get_daily_prices_v5_un,
        'period': 7 * 24,  # не используется - метод всегда отдаёт текущий срез цен
        'init_period': 90 * 24,  # не используется
        'skip_fields': [],
        'que': ['2']
    },
    {
        'type': 'ozon',
        'table': 'ozon_prices',  # текущий срез цен (перезаписывается) - только после ozon_daily_prices!!!
        'index_fields': ['offer_id', 'client_id'],
        'cache_key': 'prices',
        'func': ozon.get_prices_v5_un,
        'period': 7 * 24,  # не используется - метод всегда отдаёт текущий срез цен
        'init_period': 90 * 24,  # не используется
        'skip_fields': [],
        'que': ['2']
    },
    {
        'type': 'ozon_perfomance',
        'table': 'ozon_advert_api',
        'index_fields': ['date', 'campaign_id', 'sku', 'order_id', 'client_id'],
        'func': ozon_perfomance.get_perfomance_full_stat_un,
        'period': 7 * 24,  # hours 14*24
        'init_period': 30 * 24,
        'skip_fields': None,
        'que': ['4']
    },
]
########################################################################################################################

TEST_MODE = False
TEST_CLIENTS = ['5']        # только Рынок
TEST_TABLES = ['ozon_advert_api']  # только рекламу
TEST_SINCE = 48
TEST_TO = 0


if __name__ == "__main__":
    script_file_name = os.path.basename(__file__)
    logging.basicConfig(handlers=[logging.FileHandler(filename=os.path.join(DIR_DATA, f"log_{script_file_name.split('.')[0]}.txt"), encoding='utf-8', mode='a+')],
                        format='[%(asctime)s] [%(levelname)s] => %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S', level=logging.INFO)
    logging.info("-" * 50)

    def _excepthook(exc_type, exc_value, exc_tb):
        logging.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
        notify_error(script_file_name, exc_value)
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    args = sys.argv
    arg_str = str(args[1]).strip() if len(args) > 1 else None
    logging.info(f'Script {script_file_name} START (arg {arg_str})')

    ####################################################### TESTS ######################################################
    # perfomance_token = ozon_perfomance.get_perfomance_token('ZwBig-j8gHAW9CztWOFMsJiL81a6_MDo2Q7xnnrBt3zZPxiNZCVPh5Zy7ZXovfqAGARZEmU5lru4ny4zPA', '14816956-1694599339491@advertising.performance.ozon.ru')
    # ozon_perfomance_headers = ozon_perfomance.get_perfomance_headers(perfomance_token)
    # print(ozon_perfomance_headers)
    #
    # test = ozon_perfomance.get_perfomance_stat_un(ozon_perfomance_headers, '2024-09-20', '2024-09-24')
    # ozon_main_headers = ozon.get_headers(60178, '4f6af733-50ce-4ff6-99a7-38b803a2aca2')
    # test = ozon.get_categories_v2_un(ozon_main_headers, '2024-12-01', '2024-12-31')
    # ozon_types_dict = ozon.get_categories_tree(ozon_main_headers)
    # for elem in test:
    #     print(elem)
    # sys.exit()
    ####################################################################################################################

    ############################################# Read accounts from config ############################################
    try:
        accounts = list(lib.read_xlsx_to_dict(os.path.join(DIR_DATA, ACCOUNTS_XLSX_FILE)).values())[0]
    except Exception as e:
        logging.warning(str(e) + " FINISH")
        notify_error(script_file_name, e)
        sys.exit()
    # logging.info(accounts)
    ####################################################################################################################

    db = Database(PSQL_DATABASE, PSQL_USER, PSQL_PASW, PSQL_HOST, PSQL_PORT)
    if not db.conn:
        logging.warning("DB connection error - FINISH")
        notify_error(script_file_name, "DB connection error")
        sys.exit()

    for account in accounts:
        client_id = str(account.get('client_id', ''))
        if not client_id or client_id == 'None':
            continue
        if TEST_MODE and client_id not in TEST_CLIENTS:
            continue

        account_name = account.get('client_name', '')
        ozon_token = account.get('ozon_token')
        ozon_client_id = account.get('ozon_client_id')
        ozon_perfomance_key = account.get('ozon_perfomance_key')
        ozon_perfomance_id = account.get('ozon_perfomance_id')
        status_flag = account.get('ozon_status', '')
        logging.info(f"Process account {account_name} - {client_id}")

        ozon_main_headers = None
        if ozon_token and ozon_client_id:
            ozon_main_headers = ozon.get_headers(ozon_client_id, ozon_token)
        ozon_perfomance_headers = None

        cache = dict()
        for entity in ENTITIES:
            table = entity.get('table')
            que_str_list = entity.get('que', [])
            if arg_str and arg_str not in que_str_list:
                logging.info(f"Table {table}, table_que {que_str_list} != run_que {arg_str} - skip")
                continue

            ############################################ Choose ozon_headers ###########################################
            type = entity.get('type', '') 
            
            if type == 'ozon_perfomance' and not ozon_perfomance_headers:
                if ozon_perfomance_key and ozon_perfomance_id:
                    perfomance_token = ozon_perfomance.get_perfomance_token(ozon_perfomance_key, ozon_perfomance_id)
                    if not perfomance_token:
                        logging.warning(f"Error recieving perfomnce_token for client_id {client_id}")
                        continue
                    ozon_perfomance_headers = ozon_perfomance.get_perfomance_headers(perfomance_token)
                else:
                    logging.warning(f"No ozon_perfomance_key or ozon_client_id for client_id {client_id}, table {table}")
                    continue

            if type == 'ozon' and not ozon_main_headers:
                logging.warning(f"No headers for client_id {client_id}, table {table}")
                continue

            if type == 'ozon_perfomance':
                ozon_headers = ozon_perfomance_headers
            else:
                ozon_headers = ozon_main_headers
            ############################################################################################################

            func = entity.get('func')
            if TEST_MODE and TEST_TABLES and table not in TEST_TABLES:
                continue
            index_fields = entity.get('index_fields', [])
            if not index_fields:
                index_fields = ['id']
            norm_index_fields = [lib.camel_to_snake(index_field) for index_field in index_fields]
            agregate_index_field = '_'.join(norm_index_fields)
            agregate_index_fields = [agregate_index_field]
            agregate_index_field_set = set()

            if not func or not table:
                continue

            ######################################### Date format for requests #########################################
            date_format = WB_DATE_FORMAT
            datetime_format = WB_DATETIME_FORMAT
            request_dt_format = ozon.OZON_DATETIME_FORMAT
            if table in ['ozon_perfomance_statistics', 'ozon_analytics', 'ozon_fbo_orders_report', 'ozon_fbs_orders_report', 'ozon_advert_api']:
                request_dt_format = date_format

            last_hours = entity.get('period')
            if TEST_MODE and TEST_SINCE:
                last_hours = TEST_SINCE
            if status_flag == 'new':
                last_hours = entity.get('init_period')
            dt_now = datetime.datetime.now()
            dt_to_str = dt_now.strftime(request_dt_format)
            if TEST_MODE and TEST_TO:
                dt_to = dt_now - datetime.timedelta(hours=TEST_TO)
                dt_to_str = dt_to.strftime(request_dt_format)
            dt_since_obj = dt_now - datetime.timedelta(hours=last_hours)
            dt_since_str = dt_since_obj.strftime(request_dt_format)

            if entity.get('dt_since_str'):
                dt_since_str = entity['dt_since_str']
            if entity.get('dt_to_str'):
                dt_to_str = entity['dt_to_str']
            ############################################################################################################

            if entity.get('cache_key') and cache.get(entity['cache_key']):
                elems = cache[entity['cache_key']]
            else:
                elems = func(ozon_headers, dt_since_str, dt_to_str)
                if entity.get('cache_key'):
                    cache[entity['cache_key']] = elems

            #################################### Ручная постобработка данных из АПИ ################################
            if table in ['ozon_products_report', 'ozon_fbo_orders_report', 'ozon_fbs_orders_report']:
                elems = lib.clear_dict_keys(elems)
            elif table == 'ozon_stocks':
                ############## Предварительно очищаем таблицу #############
                query = f"update ozon_stocks set promised_amount=0, free_to_sell_amount=0, reserved_amount=0 where client_id='{client_id}'"
                if not db.test():
                    db.reconnect()
                res = db.write_query(query)
                logging.info(f"Zero stocks in ozon_stocks = {res}")
                ###########################################################
                for elem in elems:
                    if not elem.get('idc'):
                        elem['idc'] = 0
            elif table in ['ozon_daily_stocks', 'ozon_stocks_analytic']:
                for elem in elems:
                    if not elem.get('idc'):
                        elem['idc'] = 0
            elif table == 'ozon_finance_transaction':
                for elem in elems:
                    if not elem.get('posting_order_date'): #TODO elem.get('posting', {}).get('order_date')
                        elem['posting_order_date'] = elem.get('operation_date')
                    elem['items_length'] = len(elem.get('items', []))
            elif table in ['ozon_fbs_orders', 'ozon_fbs_orders2']:
                for elem in elems:
                    if not elem.get('delivering_date'):
                        elem['delivering_date'] = elem.get('shipment_date')

            if table in ['ozon_fbs_orders_report', 'ozon_fbo_orders_report']:
                for elem in elems:
                    if not elem.get('data_otgruzki'):
                        elem['data_otgruzki'] = elem.get('prinjat_v_obrabotku')
                    if not elem.get('data_dostavki'):
                        elem['data_dostavki'] = elem.get('prinjat_v_obrabotku')
                    if not elem.get('fakticheskaja_data_peredachi_v_dostavku'):
                        elem['fakticheskaja_data_peredachi_v_dostavku'] = elem.get('prinjat_v_obrabotku')
            ########################################################################################################

            logging.info(f"Recieved {len(elems)} items from API for {table} from {dt_since_str} to {dt_to_str}")
            if not elems:
                continue

            if not db.test():
                db.reconnect()

            flag = True
            add_flag = True
            template_fields_dict = {}
            i = 0
            err = 0
            for elem in elems:
                ### FIXME
                # print(elem)
                # # if elem.get('operation_id') == 27649193239:
                # #     print(elem)
                # continue
                ### FIXME
                elem['client_id'] = client_id

                if index_fields == ['id']:
                    elem['id'] = i + 1
                stop_flag = False
                agregate_index_value = ''
                for index_field in index_fields:
                    if not elem.get(index_field):
                        stop_flag = True
                if stop_flag:
                    logging.warning(f"No index fields {index_fields} in {elem}")
                    err += 1
                    continue

                flat_dict = {}
                lib.normalize_dict(elem, flat_dict, '', skip_fields=entity.get('skip_fields'), date_format=date_format, datetime_format=datetime_format, limit_list_fields=entity.get('limit_list_fields'))
                if agregate_index_field not in flat_dict:
                    flat_dict[agregate_index_field] = '_'.join([str(flat_dict.get(index_key)) for index_key in norm_index_fields])
                # if flat_dict[agregate_index_field] in agregate_index_field_set:
                #     logging.warning(f"Table {table} index field already in db, value - {flat_dict[agregate_index_field]}, field - {agregate_index_field}")
                agregate_index_field_set.add(flat_dict[agregate_index_field])

                if flag:
                    init_template_fields_dict = lib.make_pg_dict_template(flat_dict, preset_fields_types_dict=entity.get('preset_fields_types_dict'))
                    # print('our', template_fields_dict)
                    agregate_index_fields = db.create_table_from_dict_template(table, init_template_fields_dict, index_fields=agregate_index_fields)
                    if not agregate_index_fields:
                        logging.warning(f"Error create_table_from_dict_template")
                        break
                    template_fields_dict = db.get_fields_dict(table)
                    flag = False

                    fields_diff = init_template_fields_dict.keys() - template_fields_dict.keys()
                    if fields_diff:
                        for field in fields_diff:
                            # field_type = lib.recoginze_pg_value_type(flat_dict[field])
                            field_type = init_template_fields_dict[field]
                            if db.add_table_column(table, field, field_type):
                                template_fields_dict[field] = field_type
                            else:
                                add_flag = False
                                logging.warning(f"Error add_table_column")
                                break
                else:
                    fields_dict = lib.make_pg_dict_template(flat_dict, preset_fields_types_dict=entity.get('preset_fields_types_dict'))
                    fields_diff = fields_dict.keys() - template_fields_dict.keys()
                    if fields_diff:
                        for field in fields_diff:
                            # field_type = lib.recoginze_pg_value_type(flat_dict[field])
                            field_type = fields_dict[field]
                            if db.add_table_column(table, field, field_type):
                                template_fields_dict[field] = field_type
                            else:
                                add_flag = False
                                logging.warning(f"Error add_table_column")
                                break
                # print(template_fields_dict)
                if not add_flag: #FIXME 08/12
                    add_flag = True
                    logging.warning(f"Error add_flag")
                    err += 1
                    continue

                if db.insert_update_item(table, flat_dict, agregate_index_fields):
                    i += 1
                else:
                    err += 1
            logging.info(f"Totaly insert/update {i} (errors {err}) in table {table}")
            logging.info(f"Totaly {len(agregate_index_field_set)} uniq index values in table {table}")
        logging.info('-'*100)

    db.close()
    logging.info('FINISH')
    notify_success(script_file_name)
    sys.exit()
