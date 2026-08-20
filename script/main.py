# -- coding: utf-8 --
"""
Автор: Олег Шабалов
Контакты: 89179021656, @olegshabalov

Выгрузка данных из ВБ в базу
"""

import datetime
import logging
import sys
import os

from db import Database
import wb
import lib
from telegram_bot.notifier import notify_success, notify_error

from settings import DIR_DATA, WB_DATE_FORMAT, WB_DATETIME_FORMAT, ACCOUNTS_XLSX_FILE, PSQL_DATABASE, PSQL_USER, \
    PSQL_PASW, PSQL_HOST, \
    PSQL_PORT, MAX_STR_SIZE

####################################################### ENTITIES #######################################################
# {
#     'type': 'wb',
#     'table': 'wb_report',
#     'index_fields': ['srid', 'realizationreport_id', 'supplier_oper_name'],
#     'func': wb.get_report_un,
#     'period': 90*24,  # hours 14*24
#     'skip_fields': None,  # list
#     # 'dt_since_str': '2024-06-10T00:00:00',
#     # 'dt_to_str': '2024-06-16T23:59:59'
# },
#     # {
#     #     'type': 'wb',
#     #     'table': 'wb_products',
#     #     'index_fields': ['nmID'],
#     #     'func': wb.get_cards_un,
#     #     'period': 0,  # hours
#     #     'init_period': 0,
#     #     'skip_fields': ['photos', 'characteristics', 'tags']  # list
#     # },
#     # {
#     #     'type': 'wb',
#     #     'table': 'wb_products',
#     #     'index_fields': ['nmID'],
#     #     'func': wb.get_cart_cards_un,
#     #     'period': 0,  # hours
#     #     'init_period': 0,
#     #     'skip_fields': ['photos', 'characteristics', 'tags']  # list
#     # },
# {
#     'type': 'wb',
#     'table': 'wb_adverts',
#     'index_fields': ['updTime'],
#     'func': wb.get_adverts_un,
#     'period': 14 * 24,  # Отчет Upd период не более 30дн 14*24
#     'init_period': 30 * 24,
#     'skip_fields': []  # list
# },
# {
#     'type': 'wb',
#     'table': 'wb_adverts2',
#     'index_fields': ['updTime', 'upd_num', 'advert_id', 'client_id'], #FIXME updNum, advertId
#     'func': wb.get_adverts_un,
#     'period': 30*24, # Отчет Upd период не более 30дн 14*24 #FIXME 14
#     'init_period': 30*24,
#     'skip_fields': []  # list
# },
# {
#     'type': 'wb',
#     'table': 'wb_stocks',
#     'index_fields': ['supplierArticle', 'warehouseName'],
#     'func': wb.get_stocks_un,
#     'period': 1000,  # hours
#     'init_period': 1000,
#     'skip_fields': None  # list
# },

ENTITIES = [
    {
        'type': 'wb',
        'table': 'wb_orders',
        'index_fields': ['srid'],
        'func': wb.get_orders_un,
        'period': 7*24, #hours 14*24
        'init_period': 30*24,
        'skip_fields': None,
        'que': '1'
    },
    {
        'type': 'wb',
        'table': 'wb_sales',
        'index_fields': ['srid'],
        'func': wb.get_sales_un,
        'period': 7*24,  # hours 7*24
        'init_period': 30*24,
        'skip_fields': None,
        'que': '2'
    },
    {
        'type': 'wb',
        'table': 'wb_incomes',
        'index_fields': ['incomeId', 'nmId'],
        'func': wb.get_incomes_un,
        'period': 7*24,  # hours 7*24
        'init_period': 30*24,
        'skip_fields': None,
        'que': '2'
    },
    {
        'type': 'wb',
        'table': 'wb_stocks2',
        # index_fields обновлены под новый метод stocks-report/wb-warehouses (нет supplierArticle/barcode)
        'index_fields': ['nmId', 'chrtId', 'warehouseId'],
        'func': wb.get_stocks_un,
        'period': 1000,  # hours
        'init_period': 1000,
        'skip_fields': None,
        'que': '2'
    },
    {
        'type': 'wb',
        'table': 'wb_daily_stocks',
        # index_fields обновлены под новый метод stocks-report/wb-warehouses (нет supplierArticle/barcode)
        'index_fields': ['nmId', 'chrtId', 'warehouseId', 'date'],
        'func': wb.get_daily_stocks_un,
        'period': 1000,  # hours
        'init_period': 1000,
        'skip_fields': None,
        'que': '1'
    },
    {
        'type': 'wb',
        'table': 'wb_paid_storage',
        'index_fields': ['giId', 'nmId', 'chrtId', 'officeId', 'warehousePrice', 'date', 'client_id'],
        'func': wb.get_storage_report_un,
        'period': 7*24,  # Difference between dateFrom and dateTo should be less or equal 8 days
        'init_period': 7*24,
        'skip_fields': None,
        'que': '2',
        'preset_fields_types_dict': {'tariff_fix_date': f'VARCHAR({MAX_STR_SIZE})'} #поле tariff_fix_date сделать varchar
    },
    {
        'type': 'wb',
        'table': 'wb_products3',
        'index_fields': ['nmID', 'chrtID', 'skus'],
        'func': wb.get_cards_un_v2,
        'period': 0,  # hours
        'init_period': 0,
        'skip_fields': ['characteristics', 'tags', 'sizes'],  # 'photos'
        'que': '2'
    },
    {
        'type': 'wb',
        'table': 'wb_products3',
        'index_fields': ['nmID', 'chrtID', 'skus'],
        'func': wb.get_cart_cards_un_v2,
        'period': 0,  # hours
        'init_period': 0,
        'skip_fields': ['characteristics', 'tags', 'sizes'],  # 'photos'
        'que': '2'
    },
    {
        'type': 'wb',
        'table': 'wb_adverts3',
        'index_fields': ['updTime', 'updSum', 'advertId', 'client_id'],
        'func': wb.get_adverts_un,  # WB_DATE_FORMAT
        'period': 14 * 24,  # Отчет Upd период не более 30дн 14*24
        'init_period': 30 * 24,
        'skip_fields': [],
        'que': '2'
    },
    {
        'type': 'wb',
        'table': 'wb_adverts_stat', #{"error":"некорректные параметры запроса: количество кампаний в запросе не должно превышать 100"}
        # В 6м кабинете только ошибка - ALTER TABLE wb_adverts_stat ADD COLUMN apps_3_nm_17_shks BIGINT- tables can have at most 1600 columns
        'index_fields': ['date', 'advertId', 'client_id'],
        'func': wb.get_adverts_stat_un,
        'period': 14*24, #14 Отчет Upd период не более 30дн - из него получаем AdvertsId 14*24
        'init_period': 30*24,
        'skip_fields': [], #['apps']  # list
        'que': '0'
    },
    {
        'type': 'wb',
        'table': 'wb_adverts_stat_v2',
        'index_fields': ['date', 'advertId', 'client_id'],
        'func': wb.get_adverts_stat_un_v2,
        'period': 7 * 24,
        'init_period': 30 * 24,
        'skip_fields': ['apps'],  # ['apps']
        'que': '1'
    },
    {
        'type': 'wb',
        'table': 'wb_adverts_stat_v3',
        'index_fields': ['date', 'appType', 'nmId', 'advertId', 'client_id'],
        'func': wb.get_adverts_stat_un_v3,
        'period': 7 * 24,
        'init_period': 30 * 24,
        'skip_fields': ['apps'],  # ['apps']
        'que': '2'
    },
    # {
    #     'type': 'wb',
    #     'table': 'wb_analytics', #TODO - устарела!!!
    #     'index_fields': ['date', 'nmID'],
    #     'func': wb.get_analytics_un,
    #     'period': 7*24, # 14*24
    #     'init_period': 30*24,
    #     'skip_fields': [],
    #     'que': '2'
    # },
    {
        'type': 'wb',
        'table': 'wb_analytics_v2',  # периодически надо чистить analytic_report_temp
        'index_fields': ['dt', 'nmID'],
        'func': wb.get_analytic_report_un,
        'period': 7 * 24,  # 14*24
        'init_period': 30 * 24,
        'skip_fields': [],
        'que': '2'
    },
    {
        'type': 'wb',
        'table': 'wb_promo_products',
        'index_fields': ['id', 'action_id', 'client_id'],
        'func': wb.get_promo_products_un,
        'period': 7 * 24,  # don't use
        'init_period': 30 * 24, # don't use
        'skip_fields': [],
        'que': '2'
    },
    {
        'type': 'wb',
        'table': 'wb_prices',
        'index_fields': ['nmID', 'sizeID', 'client_id'],
        'func': wb.get_prices_un,
        'period': 7 * 24,  # don't use - метод всегда отдаёт текущий снимок цен
        'init_period': 30 * 24,  # don't use
        'skip_fields': [],
        'que': '2'
    },
    {
        'type': 'wb',
        'table': 'wb_report_rrd_day',
        'index_fields': ['rrd_id', 'realizationreport_id', 'supplier_oper_name'],
        'func': wb.get_report_day_un,
        'period': 7 * 24,  # hours 14*24
        'init_period': 30 * 24,
        'skip_fields': None,  # list
        # 'dt_since_str': '2024-06-10T00:00:00',
        # 'dt_to_str': '2024-06-16T23:59:59'
        'que': '3'
    },
    {
        'type': 'wb',
        'table': 'wb_report_rrd',
        'index_fields': ['rrd_id', 'realizationreport_id', 'supplier_oper_name'],
        'func': wb.get_report_un,
        'period': 14 * 24,  # hours 14*24
        'init_period': 30 * 24,
        'skip_fields': None,  # list
        # 'dt_since_str': '2024-06-10T00:00:00',
        # 'dt_to_str': '2024-06-16T23:59:59'
        'que': '2',
        'preset_fields_types_dict': {'fix_tariff_date_from': f'VARCHAR({MAX_STR_SIZE})', 'fix_tariff_date_to': f'VARCHAR({MAX_STR_SIZE})'} #fix_tariff_date_from, fix_tariff_date_to - сделать вручную тип полей Varchar(255)
    },
    {
        'type': 'wb',
        'table': 'wb_media_adverts_stat',
        'index_fields': ['date', 'item_id', 'app_type', 'client_id'],
        'func': wb.get_media_adverts_stat_un,
        'period': 0, # настраивается внутри wb.get_media_adverts_stat_un
        'init_period': 0,
        'skip_fields': [],  # ['apps']
        'que': '3'
    },
]
########################################################################################################################

MANUAL = False #FIXME
CLIENT_IDS = ['86'] #Media - '110', '136', '142'
MANUAL_STATUS = None
TABLES_TO_PERIODS = {
    # 'wb_media_adverts_stat': ('2025-08-03', '2025-08-25'),
    # 'wb_orders': ('2025-08-03', '2025-08-25'),
    # 'wb_report_rrd_day': ('2026-03-23', '2026-03-30'),
    # 'wb_report_rrd': ('2025-11-28', '2025-12-05'),
    # 'wb_adverts_stat': ('2025-10-14', '2025-11-13'),
    # 'wb_adverts_stat_v3': ('2026-03-01', '2026-03-30'),
    'wb_analytics_v2': ('2026-03-14', '2026-03-30'),
}


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

    #################################### tests ######################################
    # token = 'eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjUwOTA0djEiLCJ0eXAiOiJKV1QifQ.eyJlbnQiOjEsImV4cCI6MTc3NTU4NzA5NywiaWQiOiIwMTk5YmQ2NC02NDE5LTdiNmEtYmY0My0xMTA3YTU4ZmYwZjYiLCJpaWQiOjMwMjE1NzkzMSwib2lkIjoyNTAwNDEyODAsInMiOjEwNzM3NTc5NTAsInNpZCI6ImYyODlmYzMxLTI3OGUtNDM5ZS1iZTQwLTFkOGZlNDEzZWVjYyIsInQiOmZhbHNlLCJ1aWQiOjMwMjE1NzkzMX0.PoINQMiMxmslW63L8F0YuZCAqExwlbe4Js9z0oYa_w1n0BOuwxVivzPtYb0PmNZPMzz6xw65Jd6MEyo1UPYkFQ '
    # advs = wb.get_media_adverts_stat_un(token)
    # for adv in advs:
    #     print(adv)
    # dt_now = datetime.datetime.now()
    # dt_to_str = dt_now.strftime(WB_DATE_FORMAT)
    # dt_since_obj = dt_now - datetime.timedelta(hours=24*32)
    # dt_since_str = dt_since_obj.strftime(WB_DATE_FORMAT)
    # wb.get_analytic_report_un(token, dt_since_str, dt_to_str)
    # test = wb.get_promo_products_un(wb_token, dt_since_str, dt_to_str)
    # for elem in test:
    #     print(str(elem).encode('cp1251', 'ignore').decode('cp1251'))
    # print(test[0].get('date'), test[-1].get('date'))
    # print(len(test))
    # id = '6caf98de-c620-4ae0-af79-f4a1290cacc1'
    # wb.get_analytic_report_status(token, id)
    # print(wb.get_analytic_report_done(token, id))
    # sys.exit()
    ################################################################################

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
        if MANUAL and CLIENT_IDS and client_id not in CLIENT_IDS:
            continue

        # if client_id != '35':
        #     continue

        account_name = account.get('client_name', '')
        ozon_token = account.get('ozon_token')
        ozon_client_id = account.get('ozon_client_id')
        wb_token = account.get('wb_token')

        status_flag = account.get('status', '').strip() if account.get('status') else ''
        if MANUAL_STATUS:
            status_flag = MANUAL_STATUS
        if status_flag == 'stop':
            continue

        #################################### tests ######################################
        # dt_now = datetime.datetime.now()
        # dt_to_str = dt_now.strftime(WB_DATE_FORMAT)
        # dt_since_obj = dt_now - datetime.timedelta(hours=24*30)
        # dt_since_str = dt_since_obj.strftime(WB_DATE_FORMAT)
        # test = wb.get_cards_un_v2(wb_token, dt_since_str, dt_to_str)
        # text = f'Total {len(test)} items:\n\n'
        # for elem in test:
        #     print(str(elem).encode('cp1251', 'ignore').decode('cp1251'))
        #     text += str(elem).encode('cp1251', 'ignore').decode('cp1251') + '\n'
        # print(len(test))
        # with open(f"{client_id}.txt", 'w') as f:
        #     f.write(text)
        # continue
        ################################################################################

        logging.info(f"Process account {account_name} - {client_id}: {'wb' if wb_token else ''} {'ozon' if ozon_token else ''}, {status_flag}")
        for entity in ENTITIES:
            table = entity.get('table')
            if MANUAL and TABLES_TO_PERIODS and table not in TABLES_TO_PERIODS:
                continue
            que_str = entity.get('que', '')
            if arg_str and que_str != arg_str:
                logging.info(f"Table {table}, que {que_str} - skip")
                continue
            func = entity.get('func')
            index_fields = entity.get('index_fields', [])
            if not index_fields:
                index_fields = ['id']
            norm_index_fields = [lib.camel_to_snake(index_field) for index_field in index_fields]
            agregate_index_field = '_'.join(norm_index_fields)
            agregate_index_fields = [agregate_index_field]
            agregate_index_field_set = set()

            if not func or not table:
                continue

            elems = []
            date_format = None
            if entity['type'] == 'wb' and wb_token:
                datetime_format = WB_DATETIME_FORMAT
                date_format = WB_DATE_FORMAT
                request_dt_format = datetime_format
                if table in ['wb_adverts2', 'wb_adverts3', 'wb_adverts_stat', 'wb_analytics', 'wb_adverts_stat_v2',
                             'wb_analytics_v2', 'wb_adverts_stat_v3']:
                    request_dt_format = date_format

                last_hours = entity.get('period')
                if status_flag == 'new':
                    last_hours = entity.get('init_period')
                if MANUAL and TABLES_TO_PERIODS.get(table):
                    (start_date, end_date) = TABLES_TO_PERIODS[table]
                    dt_since_str = datetime.datetime.strptime(start_date, WB_DATE_FORMAT).strftime(request_dt_format)
                    dt_to_str = datetime.datetime.strptime(end_date, WB_DATE_FORMAT).strftime(request_dt_format)
                else:
                    dt_now = datetime.datetime.now()
                    dt_to_str = dt_now.strftime(request_dt_format)
                    dt_since_obj = dt_now - datetime.timedelta(hours=last_hours)
                    dt_since_str = dt_since_obj.strftime(request_dt_format)

                if entity.get('dt_since_str'):
                    dt_since_str = entity['dt_since_str']
                if entity.get('dt_to_str'):
                    dt_to_str = entity['dt_to_str']

                elems = func(wb_token, dt_since_str, dt_to_str)

                if table in ['wb_adverts2', 'wb_adverts3']: #FIXME
                    for elem in elems:
                        if not elem.get('updTime'):
                            elem['updTime'] = datetime.datetime.now().strftime(WB_DATETIME_FORMAT)

                if table in ['wb_report_rrd_day', 'wb_report_rrd']:
                    for elem in elems:
                        if elem.get('bonus_type_name') and ', документ' in elem['bonus_type_name']:
                            elem['bonus_type_name'] = elem['bonus_type_name'].split(', документ')[0]

                logging.info(f"Recieved {len(elems)} items from API for {table} from {dt_since_str} to {dt_to_str}")

            elif entity['type'] == 'ozon' and ozon_token:
                # elems = func(wb_token, last_hours=entity.get('period'))
                # date_format = WB_DATE_FORMAT
                pass

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
                # logging.info(elem) #FIXME
                elem['client_id'] = client_id

                if index_fields == ['id']:
                    elem['id'] = i + 1
                stop_flag = False
                agregate_index_value = ''
                for index_field in index_fields:
                    if elem.get(index_field) is None:
                        stop_flag = True
                if stop_flag:
                    if table not in ['wb_paid_storage', 'wb_adverts2', 'wb_adverts3']:
                        logging.warning(f"No index fields {index_fields} in {elem}")
                        err += 1
                        continue

                flat_dict = {}
                lib.normalize_dict(elem, flat_dict, '', skip_fields=entity.get('skip_fields'), date_format=date_format, datetime_format=datetime_format)
                if agregate_index_field not in flat_dict:
                    flat_dict[agregate_index_field] = '_'.join([str(flat_dict.get(index_key)) for index_key in norm_index_fields])
                # if flat_dict[agregate_index_field] in agregate_index_field_set:
                #     logging.warning(f"Table {table} index field already in db, value - {flat_dict[agregate_index_field]}, field - {agregate_index_field}")
                agregate_index_field_set.add(flat_dict[agregate_index_field])
                # print('-'*50)
                # print(elem)
                # print(flat_dict)
                # continue

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
                        if table in ['wb_adverts_stat']: #, 'wb_adverts_stat_v3'
                            new_flat_dict = dict()
                            for key in template_fields_dict:
                                new_flat_dict[key] = flat_dict.get('key')
                            flat_dict = new_flat_dict
                        else:
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
                        if table in ['wb_adverts_stat']: #, 'wb_adverts_stat_v3'
                            new_flat_dict = dict()
                            for key in template_fields_dict:
                                new_flat_dict[key] = flat_dict.get('key')
                            flat_dict = new_flat_dict
                        else:
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
                if not add_flag:
                    add_flag = True
                    logging.warning(f"Error add_flag")
                    err += 1
                    continue

                if db.insert_update_item(table, flat_dict, agregate_index_fields):
                    i += 1
            logging.info(f"Totaly insert/update {i} (errors {err}) in table {table}")
            logging.info(f"Totaly {len(agregate_index_field_set)} uniq index values in table {table}")
        logging.info('-'*100)

    db.close()
    logging.info('FINISH')
    notify_success(script_file_name)
    sys.exit()