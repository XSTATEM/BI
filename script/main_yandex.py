# -- coding: utf-8 --
"""
Автор: Олег Шабалов
Контакты: 89179021656, @olegshabalov

Выгрузка данных из Yandex в базу

1) Детальная информация по заказам (FBY) - https://yandex.ru/dev/market/partner-api/doc/ru/api/orders-stats/getOrdersStats
2) Информация о нескольких заказах (FBS) - https://yandex.ru/dev/market/partner-api/doc/ru/api/orders/getOrders
3) Список невыкупов и возвратов - https://yandex.ru/dev/market/partner-api/doc/ru/reference/orders/getReturns
4) Информация о товарах, которые размещены в заданном магазине - https://yandex.ru/dev/market/partner-api/doc/ru/reference/assortment/getCampaignOffers
5) Информация об остатках и оборачиваемости - https://yandex.ru/dev/market/partner-api/doc/ru/reference/stocks/getStocks
6) Просмотр цен на указанные товары в магазине - https://yandex.ru/dev/market/partner-api/doc/ru/reference/assortment/getPricesByOfferIds
6) Информация о ценах и сопоставлении товаров

7) Получение списка товаров, которые участвуют или могут участвовать в акции - https://yandex.ru/dev/market/partner-api/doc/ru/reference/promos/getPromoOffers
8), 9) Отчет по заказам - https://yandex.ru/dev/market/partner-api/doc/ru/reference/reports/generateUnitedOrdersReport
здесь 2 таблицы: Транзакции по заказам, Услуги по заказам -
"""

import datetime
import logging
import sys
import os
import time
from pathlib import Path

from db import Database
import ya
import lib
from telegram_bot.notifier import notify_success, notify_error

from settings import DIR_DATA, PSQL_DATABASE, PSQL_USER, PSQL_PASW, PSQL_HOST, \
    PSQL_PORT

#################################################### ACCOUNTS ##########################################################
ACCOUNTS = [
    {
        'client_id': 2,
        'name': 'Ечипс Импорт',
        'business_id': 89672278,
        'campaings': [
            {'id': 80802513, 'name': 'Ечипс Импорт 2 FBY', 'type': 'FBY'},
            {'id': 148953057, 'name': 'Сертификат_BigShop DBS', 'type': 'DBS'},
        ],
        'status': ''  # 'new' только для первичной загрузки: с ним каждый прогон качает init_period (30-90 дней) вместо period
    }
]

####################################################### ENTITIES #######################################################
ENTITIES = [
    {
        'type': 'excel',
        'excel_group': 'marketplace_services',
        'excel_sheet': 'Программа лояльности и отзывы',
        'excel_fields': [
            'id_biznes_akkaunta', 'modeli_raboty', 'id_magazinov', 'nazvanija_magazinov',
            'inn', 'nomera_dogovorov_na_razmeschenie', 'nomera_dogovorov_na_prodvizhenie',
            'nomer_zakaza_ili_otgruzki', 'vash_sku', 'nazvanie_tovara',
            'vasha_tsena_za_sht', 'pokupatel_zaplatil', 'kolichestvo_sht', 'usluga',
            'id_otzyva', 'tarif_za_sht', 'stavka_po_aktsii', 'kolichestvo_ballov',
            'skidka', 'oplata_bonusami', 'data_i_vremja_okazanija_uslugi',
            'data_formirovanija_akta', 'stoimost_uslugi'
        ],
        'excel_values_row': 2,
        'excel_header_row': None,
        'excel_sub_header_row': None,
        'table': 'ya_mp_loyalty',
        'index_fields': ['nomer_zakaza_ili_otgruzki', 'vash_sku', 'client_id'],
        'period': 14 * 24,
        'init_period': 90 * 24,
        'skip_fields': [],
        'que': '4'
    },
    {
        'type': 'excel',
        'excel_group': 'marketplace_services',
        'excel_sheet': 'Поставка через транзитный склад',
        'excel_fields': [
            'id_biznes_akkaunta', 'modeli_raboty', 'id_magazinov', 'nazvanija_magazinov',
            'inn', 'nomera_dogovorov_na_razmeschenie', 'nomera_dogovorov_na_prodvizhenie',
            'nomer_postavki_market', 'nomer_postavki_sklad', 'postavka_neskolko_skladov',
            'kolichestvo_napravlenij', 'paleta_ili_korobka', 'dolja_turbo',
            'tarif_za_sht', 'kolichestvo_sht', 'skidka_protsent', 'skidka_rub',
            'usluga', 'data_okazanija_uslugi', 'data_formirovanija_akta', 'stoimost_uslugi'
        ],
        'excel_values_row': 2,
        'excel_header_row': None,
        'excel_sub_header_row': None,
        'table': 'ya_mp_transit',
        'index_fields': ['nomer_postavki_market', 'client_id'],
        'period': 14 * 24,
        'init_period': 90 * 24,
        'skip_fields': [],
        'que': '4'
    },
    {
        'type': 'excel',
        'excel_group': 'marketplace_services',
        'excel_sheet': 'Вывоз со склада, СЦ, ПВЗ',
        'excel_fields': [
            'id_biznes_akkaunta', 'modeli_raboty', 'id_magazinov', 'nazvanija_magazinov',
            'inn', 'nomera_dogovorov_na_razmeschenie', 'nomera_dogovorov_na_prodvizhenie',
            'nomer_zayavki_market', 'nomer_zayavki_sklad', 'sklad', 'vash_sku',
            'nazvanie_tovara', 'stok', 'ocenochnaja_stoimost', 'kolichestvo_sht',
            'ves_kg', 'dlina_sm', 'shirina_sm', 'vysota_sm', 'summa_treh_izmerenij_sm',
            'usluga', 'tarif_za_sht', 'data_i_vremja_okazanija_uslugi',
            'data_formirovanija_akta', 'stoimost_uslugi'
        ],
        'excel_values_row': 2,
        'excel_header_row': None,
        'excel_sub_header_row': None,
        'table': 'ya_mp_pickup',
        'index_fields': ['nomer_zayavki_market', 'vash_sku', 'client_id'],
        'period': 14 * 24,
        'init_period': 90 * 24,
        'skip_fields': [],
        'que': '4'
    },
    {
        'type': 'excel',
        'excel_group': 'marketplace_services',
        'excel_sheet': 'Организация утилизации',
        'excel_fields': [
            'id_biznes_akkaunta', 'modeli_raboty', 'id_magazinov', 'nazvanija_magazinov',
            'inn', 'nomera_dogovorov_na_razmeschenie', 'nomera_dogovorov_na_prodvizhenie',
            'nomer_zayavki_utilizatsija', 'data_sozdanija_zayavki', 'vash_sku',
            'nazvanie_tovara', 'kolichestvo_sht', 'ves_kg', 'dlina_sm', 'shirina_sm',
            'vysota_sm', 'summa_treh_izmerenij_sm', 'usluga', 'tarif',
            'data_i_vremja_okazanija_uslugi', 'data_formirovanija_akta', 'stoimost_uslugi'
        ],
        'excel_values_row': 2,
        'excel_header_row': None,
        'excel_sub_header_row': None,
        'table': 'ya_mp_utilization',
        'index_fields': ['nomer_zayavki_utilizatsija', 'vash_sku', 'client_id'],
        'period': 14 * 24,
        'init_period': 90 * 24,
        'skip_fields': [],
        'que': '4'
    },
    {
        'type': 'excel',
        'excel_group': 'marketplace_services',
        'excel_sheet': 'Подписки',
        'excel_fields': [
            'id_biznes_akkaunta', 'modeli_raboty', 'id_magazinov', 'nazvanija_magazinov',
            'inn', 'nomera_dogovorov_na_razmeschenie', 'nomera_dogovorov_na_prodvizhenie',
            'usluga', 'tarif_v_mesyats', 'data_okazanija_uslugi',
            'data_formirovanija_akta', 'stoimost_uslugi', 'kommentarij'
        ],
        'excel_values_row': 2,
        'excel_header_row': None,
        'excel_sub_header_row': None,
        'table': 'ya_mp_subscription',
        'index_fields': ['data_okazanija_uslugi', 'client_id'],
        'period': 14 * 24,
        'init_period': 90 * 24,
        'skip_fields': [],
        'que': '4'
    },
    {
        'type': 'excel',
        'excel_group': 'marketplace_services',
        'excel_sheet': 'Буст продаж, оплата за показы',
        'excel_fields': [
            'id_biznes_akkaunta', 'modeli_raboty', 'id_magazinov', 'nazvanija_magazinov',
            'inn', 'nomera_dogovorov_na_razmeschenie', 'nomera_dogovorov_na_prodvizhenie',
            'id_reklamodatelja', 'nomer_kampanii', 'nazvanie_kampanii', 'usluga',
            'pokazy_sht', 'ploshadka', 'bjudzhet', 'oplata', 'oplata_bonusami',
            'skidka_aktsii', 'data_okazanija_uslugi', 'data_formirovanija_akta', 'stoimost_uslugi'
        ],
        'excel_values_row': 2,
        'excel_header_row': None,
        'excel_sub_header_row': None,
        'table': 'ya_mp_boost_shows',
        'index_fields': ['id_reklamodatelja', 'nomer_kampanii', 'data_okazanija_uslugi', 'client_id'],
        'period': 14 * 24,
        'init_period': 90 * 24,
        'skip_fields': [],
        'que': '4'
    },
    {
        'type': 'excel',
        'excel_group': 'marketplace_services',
        'excel_sheet': 'Буст продаж, оплата за продажи',
        'excel_fields': [
            'id_biznes_akkaunta', 'modeli_raboty', 'id_magazinov', 'nazvanija_magazinov',
            'inn', 'nomera_dogovorov_na_razmeschenie', 'nomera_dogovorov_na_prodvizhenie',
            'nomer_zakaza_ili_otgruzki', 'vash_sku', 'nazvanie_tovara', 'kategorija',
            'vasha_tsena_za_sht', 'kolichestvo_sht', 'usluga', 'stavka_protsent',
            'predoplata', 'postoplata', 'oplata_bonusami', 'skidka_aktsii',
            'data_okazanija_uslugi', 'data_formirovanija_akta', 'stoimost_uslugi'
        ],
        'excel_values_row': 2,
        'excel_header_row': None,
        'excel_sub_header_row': None,
        'table': 'ya_mp_boost_sales',
        'index_fields': ['nomer_zakaza_ili_otgruzki', 'vash_sku', 'client_id'],
        'period': 14 * 24,
        'init_period': 90 * 24,
        'skip_fields': [],
        'que': '4'
    },
    {
        'type': 'excel',
        'excel_group': 'marketplace_services',
        'excel_sheet': 'Полки',
        'excel_fields': [
            'id_biznes_akkaunta', 'modeli_raboty', 'id_magazinov', 'nazvanija_magazinov',
            'inn', 'nomera_dogovorov_na_razmeschenie', 'nomera_dogovorov_na_prodvizhenie',
            'id_reklamodatelja', 'nomer_kampanii', 'nazvanie_kampanii', 'usluga',
            'pokazy_sht', 'ploshadka', 'tip_bjudzheta', 'bjudzhet', 'oplata',
            'oplata_bonusami', 'skidka_aktsii',
            'data_okazanija_uslugi', 'data_formirovanija_akta', 'stoimost_uslugi'
        ],
        'excel_values_row': 2,
        'excel_header_row': None,
        'excel_sub_header_row': None,
        'table': 'ya_mp_shelves',
        'index_fields': ['id_reklamodatelja', 'nomer_kampanii', 'data_okazanija_uslugi', 'client_id'],
        'period': 14 * 24,
        'init_period': 90 * 24,
        'skip_fields': [],
        'que': '4'
    },
    {
        'type': 'excel',
        'excel_group': 'marketplace_services',
        'excel_sheet': 'Баннеры',
        'excel_fields': [
            'id_biznes_akkaunta', 'modeli_raboty', 'id_magazinov', 'nazvanija_magazinov',
            'inn', 'nomera_dogovorov_na_razmeschenie', 'nomera_dogovorov_na_prodvizhenie',
            'id_reklamodatelja', 'nomer_kampanii', 'nazvanie_kampanii', 'usluga',
            'pokazy_sht', 'ploshadka', 'tip_bjudzheta', 'bjudzhet',
            'data_okazanija_uslugi', 'data_formirovanija_akta', 'stoimost_uslugi'
        ],
        'excel_values_row': 2,
        'excel_header_row': None,
        'excel_sub_header_row': None,
        'table': 'ya_mp_banners',
        'index_fields': ['id_reklamodatelja', 'nomer_kampanii', 'data_okazanija_uslugi', 'client_id'],
        'period': 14 * 24,
        'init_period': 90 * 24,
        'skip_fields': [],
        'que': '4'
    },
    {
        'type': 'excel',
        'excel_group': 'marketplace_services',
        'excel_sheet': 'Пуш-уведомления',
        'excel_fields': [
            'id_biznes_akkaunta', 'modeli_raboty', 'id_magazinov', 'nazvanija_magazinov',
            'inn', 'nomera_dogovorov_na_razmeschenie', 'nomera_dogovorov_na_prodvizhenie',
            'id_reklamodatelja', 'nomer_kampanii', 'nazvanie_kampanii', 'usluga',
            'pokazy_sht', 'ploshadka', 'tip_bjudzheta', 'bjudzhet',
            'data_okazanija_uslugi', 'data_formirovanija_akta', 'stoimost_uslugi'
        ],
        'excel_values_row': 2,
        'excel_header_row': None,
        'excel_sub_header_row': None,
        'table': 'ya_mp_push',
        'index_fields': ['id_reklamodatelja', 'nomer_kampanii', 'data_okazanija_uslugi', 'client_id'],
        'period': 14 * 24,
        'init_period': 90 * 24,
        'skip_fields': [],
        'que': '4'
    },
    {
        'type': 'excel',
        'excel_group': 'marketplace_services',
        'excel_sheet': 'Приём платежа',
        'excel_fields': [
            'id_biznes_akkaunta', 'modeli_raboty', 'id_magazinov', 'nazvanija_magazinov',
            'inn', 'nomera_dogovorov_na_razmeschenie', 'nomera_dogovorov_na_prodvizhenie',
            'nomer_zakaza_ili_otgruzki', 'vash_sku', 'nazvanie_tovara',
            'pokupatel_zaplatil', 'tarif_za_sht', 'edinitsa_izmerenija',
            'data_i_vremja_okazanija_uslugi', 'data_formirovanija_akta',
            'stoimost_uslugi', 'tip_zapisi'
        ],
        'excel_values_row': 5,
        'excel_header_row': None,
        'excel_sub_header_row': None,
        'table': 'ya_mp_payment_receive',
        'index_fields': ['nomer_zakaza_ili_otgruzki', 'vash_sku', 'client_id'],
        'period': 14 * 24,
        'init_period': 90 * 24,
        'skip_fields': [],
        'que': '4'
    },
    {
        'type': 'excel',
        'excel_group': 'marketplace_services',
        'excel_sheet': 'Перевод платежа',
        'excel_fields': [
            'id_biznes_akkaunta', 'modeli_raboty', 'id_magazinov', 'nazvanija_magazinov',
            'inn', 'nomera_dogovorov_na_razmeschenie', 'nomera_dogovorov_na_prodvizhenie',
            'nomer_zakaza_ili_otgruzki', 'vash_sku', 'nazvanie_tovara',
            'pokupatel_zaplatil', 'vasha_tsena', 'tarif',
            'data_i_vremja_okazanija_uslugi', 'data_formirovanija_akta',
            'stoimost_uslugi', 'tip_zapisi'
        ],
        'excel_values_row': 2,
        'excel_header_row': None,
        'excel_sub_header_row': None,
        'table': 'ya_mp_payment_transfer',
        'index_fields': ['nomer_zakaza_ili_otgruzki', 'vash_sku', 'client_id'],
        'period': 14 * 24,
        'init_period': 90 * 24,
        'skip_fields': [],
        'que': '4'
    },
    {
        'type': 'excel',
        'excel_group': 'marketplace_services',
        'excel_sheet': 'Размещение товаров на витрине',
        'excel_fields': [
            'id_biznes_akkaunta', 'modeli_raboty', 'id_magazinov', 'nazvanija_magazinov',
            'inn', 'nomera_dogovorov_na_razmeschenie', 'nomera_dogovorov_na_prodvizhenie',
            'nomer_zakaza_ili_otgruzki', 'data_sozdanija_zakaza', 'vash_sku',
            'nazvanie_tovara', 'tip_tovara', 'vasha_tsena_za_sht_rub',
            'raznitsa_tseny', 'kolichestvo_sht', 'kvant_prodazhi', 'kvantov_v_zakaze',
            'tsena_za_kvant', 'ves_kg', 'obem_l', 'dlina_sm', 'shirina_sm', 'vysota_sm',
            'summa_treh_izmerenij_sm', 'sposob_priema_oplaty', 'znachenie_indeksa_kachestva',
            'usluga', 'uslovija_tarifa', 'tarif_za_sht', 'edinitsa_izmerenija',
            'minimalnyj_tarif_za_sht', 'maksimalnyj_tarif_za_sht',
            'stoimost_uslugi_do_min_tarifa', 'data_i_vremja_okazanija_uslugi',
            'data_formirovanija_akta', 'stoimost_uslugi_bez_skidok',
            'tarif_vyzovy', 'skidka_vyzovy', 'opozdanie_dni', 'tarif_opozdanie',
            'tarif_otmena', 'min_stoimost', 'max_stoimost', 'izmenenie_stoimosti_ar',
            'tarif_umnoe', 'izmenenie_stoimosti_at', 'individualnaja_skidka',
            'skidka_za_lojalnost', 'skidka_aktsii',
            'razmeshenie_tovarov'
        ],
        'excel_values_row': 7,
        'excel_header_row': None,
        'excel_sub_header_row': None,
        'table': 'ya_marketplace_services',
        'index_fields': ['nomer_zakaza_ili_otgruzki', 'vash_sku', 'client_id'],
        'period': 14 * 24,
        'init_period': 90 * 24,
        'skip_fields': [],
        'que': '4'
    },
    {
        'type': 'campaing',
        'table': 'ya_orders_report',
        'index_fields': ['id', 'shopSku'],
        'func': ya.get_orders_report_un,
        'period': 30*24,
        'init_period': 90*24,
        'skip_fields': ['commissions', 'payments', 'items', 'subsidies'],
        'que': '1'
    },
    {
        'type': 'campaing',
        'table': 'ya_orders',
        'index_fields': ['id', 'item_offerId'],
        'func': ya.get_orders_un,
        'period': 7 * 24, #Максимальный диапазон дат за один запрос к ресурсу — 30 дней.
        'init_period': 30 * 24,
        'skip_fields': ['region', 'items', 'subsidies'],
        'que': '2'
    },
    {
        'type': 'campaing',
        'table': 'ya_returns',
        'index_fields': ['id', 'item_shopSku'],
        'func': ya.get_returns_un,
        'period': 3 * 24,
        'init_period': 30 * 24,
        'skip_fields': ['logisticPickupPoint', 'items'],
        'que': '2'
    },
    {
        'type': 'campaing',
        'table': 'ya_products',
        'index_fields': ['offerId', 'client_id'],
        'func': ya.get_offers_un,
        'period': 1 * 24,
        'init_period': 1 * 24,
        'skip_fields': [],
        'que': '2'
    },
    {
        'type': 'campaing',
        'table': 'ya_stocks',
        'index_fields': ['offer_id', 'warehouse_id', 'client_id'],
        'func': ya.get_stocks_un,
        'period': 1 * 24,
        'init_period': 1 * 24,
        'skip_fields': [],
        'que': '2'
    },
    {
        'type': 'campaing',
        'table': 'ya_daily_prices',  # историчный срез - одна строка на offerId+campaign в день
        'index_fields': ['offerId', 'campaign_id', 'client_id', 'date'],
        'cache_key': 'ya_prices',
        'func': ya.get_prices_un,
        'period': 1 * 24,
        'init_period': 1 * 24,
        'skip_fields': [],
        'que': '2'
    },
    {
        'type': 'campaing',
        'table': 'ya_prices',  # цена конкретного магазина ("В магазине") - фактическая цена на витрине; только после ya_daily_prices!!!
        'index_fields': ['offerId', 'campaign_id', 'client_id'],
        'cache_key': 'ya_prices',
        'func': ya.get_prices_un,
        'period': 1 * 24,
        'init_period': 1 * 24,
        'skip_fields': [],
        'que': '2'
    },
    {
        'type': 'business',
        'table': 'ya_daily_prices_lk',  # историчный срез цены из ЛК - одна строка на offerId в день
        'index_fields': ['offerId', 'client_id', 'date'],
        'cache_key': 'ya_prices_lk',
        'func': ya.get_default_prices_un,
        'period': 1 * 24,
        'init_period': 1 * 24,
        'skip_fields': [],
        'que': '2'
    },
    {
        'type': 'business',
        'table': 'ya_prices_lk',  # цена по кабинету ("В кабинете") - "цена из ЛК"; только после ya_daily_prices_lk!!!
        'index_fields': ['offerId', 'client_id'],
        'cache_key': 'ya_prices_lk',
        'func': ya.get_default_prices_un,
        'period': 1 * 24,
        'init_period': 1 * 24,
        'skip_fields': [],
        'que': '2'
    },
    {
        'type': 'business',
        'table': 'ya_mappings',
        'index_fields': ['offerId', 'client_id'],
        'func': ya.get_mappings_un,
        'period': 1 * 24,
        'init_period': 1 * 24,
        'skip_fields': [],
        'que': '2'
    },
    {
        'type': 'business',
        'table': 'ya_promos',
        'index_fields': ['offerId', 'promo_id', 'client_id'],
        'func': ya.get_promos_un,
        'period': 1 * 24,
        'init_period': 1 * 24,
        'skip_fields': [],
        'que': '2'
    },
    {
        'type': 'excel',
        'excel_group': 'allorders',
        'excel_sheet': 'Услуги и маржа по заказам',
        'excel_fields': ['business_id',	'schema',	'campaign_id',	'merchant',	'inn',	'dogovor_razmeshenie',	'dogovor_prodvizhenie',	'offer_id',	'merchant_offer_id',	'status',	'date',	'type',	'market_serices',	'price','revenue_after_market_services',	'payment',	'payment_status',	'platezh',	'razmeshenie_tovarov',	'sborka',	'loyal_program',	'sale_bust',	'credit',	'delivery',	'epress_delivery',	'payment_reciev',	'payment_transfer',	'orders_gather',	'order_process',	'unpaid_order_store',	'unpaid_order_return',	'reward'],
        'excel_values_row': 8,
        'excel_header_row': None,
        'excel_sub_header_row': None,
        'table': 'ya_comissions',
        'index_fields': ['offer_id', 'client_id'],
        'period': 14 * 24,
        'init_period': 90 * 24,
        'skip_fields': [],
        'que': '2'
    },
    # {
    #     'type': 'excel',
    #     'excel_group': 'allorders',
    #     'excel_sheet': 'Транзакции по заказам и товарам',
    #     'excel_fields': None,
    #     'excel_values_row': 11,
    #     'excel_header_row': 9,
    #     'excel_sub_header_row': 10,
    #     'table': 'ya_transactions_v2',
    #     'index_fields': ['nomer_zakaza', 'client_id'],
    #     'period': 14 * 24,
    #     'init_period': 90 * 24,
    #     'skip_fields': [],
    #     'que': '2'
    # },
    {
        'type': 'excel',
        'excel_group': 'allorders',
        'excel_sheet': 'Транзакции по заказам и товарам',
        'excel_fields': None,
        'excel_values_row': 11,
        'excel_header_row': 9,
        'excel_sub_header_row': 10,
        'table': 'ya_transactions_v3',
        'index_fields': ['nomer_zakaza', 'vash_sku', 'client_id'],
        'period': 14 * 24,
        'init_period': 90 * 24,
        'skip_fields': [],
        'que': '2'
    },
    {
        'type': 'zip',
        'table': 'ya_boost',
        'zip_file': 'business_boost_consolidated.json',
        'index_fields': ['shopSku', 'date', 'client_id'],
        'period': 5 * 24,
        'init_period': 30 * 24,
        'skip_fields': [],
        'que': '2'
    },
    {
        'type': 'zip',
        'table': 'ya_shelf',
        'zip_file': 'shelfs_statistics_summary.json',
        'index_fields': ['incutId', 'date', 'client_id'],
        'period': 5 * 24,
        'init_period': 30 * 24,
        'skip_fields': [],
        'que': '2'
    },
]

# {
#     'type': 'excel',
#     'excel_sheet': 'Транзакции по заказам и товарам',
#     'excel_fields': ['business_id',	'schema',	'campaign_id',	'merchant',	'inn',	'dogovor_razmeshenie',	'dogovor_prodvizhenie',
#                      'offer_id',	'merchant_offer_id',	'date',	'type',	'sku',	'product',	'count',	'count_delivery',
#                      'price',	'slae_price',	'min_price',	'merchant_diskont',	'market_discont',	'other_discont',
#                      'bonus_pay',	'points_pay',	'status',	'status_dt',	'payment_type',	'store',	'shipment_date',
#                      'region',	'customer_payment',	'customer_payment_number',	'customer_paymnet_date',	'customer_payment_id',
#                      'customer_payment_reestr_date',	'points_sum',	'points_status',	'discont_payment',	'discont_payment_number',
#                      'discont_payment_date',	'discont_payment_id',	'discont_payment_reestr_date',	'spasibo_payament',
#                      'spasibo_payment_number',	'spasibo_payment_date',	'spasibo_payment_id',	'spasibo_payment_reestr_date',
#                      'plus_payment',	'plus_payment_number',	'plus_payment_date',	'plus_payment_id',	'plus_payment_reestr_payment',
#                      'return_paymnet',	'return_paymnet_number',	'return_paymnet_date',	'return_paymnet_id',	'return_paymnet_reestr_date',
#                      'discont_return_payment',	'discont_return_payment_number',	'discont_return_payment_date',	'discont_return_payment_id',
#                      'discont_return_payment_reestr_date',	'spasibo_return',	'spasibo_return_number',	'spasibo_return_date',	'spasibo_return_id',
#                      'spasibo_return_reestr_date',	'plus_return',	'plus_return_number',	'plus_return_date',	'plus_return_id',	'plus_return_reestr_date',
#                      'customer_return',	'customer_return_number',	'customer_return_date',	'customer_return_id',	'customer_return_reestr_date'],
#     'excel_values_row': 11,
#     'excel_header_row': None,
#     'excel_sub_header_row': None,
#     'table': 'ya_transactions',
#     'index_fields': ['offer_id', 'client_id'],
#     'period': 14 * 24,
#     'init_period': 90 * 24,
#     'skip_fields': []
# },
########################################################################################################################

DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"

TEST_MODE = False
TEST_CLIENTS = ['2']
TEST_TABLES = ['ya_transactions_v3']
TEST_SINCE = 60*24 # в часах
TEST_TO = 0*24

LOCK_FILE = os.path.join(DIR_DATA, 'main_yandex.lock')
LOCK_STALE_HOURS = 3  # старый lock (упавший прошлый запуск) считаем протухшим и перезаписываем


def acquire_lock() -> bool:
    """
    Не даёт двум процессам main_yandex.py работать с одним аккаунтом одновременно -
    иначе они делят один и тот же rate limit Яндекса (например 1 запрос/2 мин на generate-отчёты)
    и обе попытки почти всегда проваливаются.
    """
    if os.path.exists(LOCK_FILE):
        age_hours = (time.time() - os.path.getmtime(LOCK_FILE)) / 3600
        if age_hours < LOCK_STALE_HOURS:
            return False
        logging.warning(f"Lock-файл старше {LOCK_STALE_HOURS}ч (возраст {age_hours:.1f}ч) - считаем протухшим, перезаписываем")
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))
    return True


def release_lock():
    try:
        os.remove(LOCK_FILE)
    except OSError:
        pass


def get_elems_from_xlsx(file_path, sheetname, fields, row):
    res = []
    raw_res = lib.read_xlsx_to_dict_v3(file_path, sheetname, row)
    for elem in raw_res:
        elem_dict = dict()
        for i, subelem in enumerate(elem):
            if i >= len(fields):
                # logging.warning("i >= len(fields)")
                continue
            if 'date' in fields[i]:
                subelem_list = str(subelem).split('.')
                if len(subelem_list) == 3:
                    subelem = f"{subelem_list[2]}-{subelem_list[1]}-{subelem_list[0]}"
            elem_dict[fields[i]] = subelem
        # строка подписей колонок, попавшая в данные (Яндекс дублирует заголовок) - пропускаем
        if str(elem_dict.get('id_biznes_akkaunta', '')) == 'ID бизнес-аккаунта':
            continue
        res.append(elem_dict)
    return res


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

    if not acquire_lock():
        logging.warning("Другой процесс main_yandex.py уже выполняется - выходим, чтобы не дублировать запросы и не упереться в rate limit Яндекса")
        sys.exit()

    ####################################################################################################################
    # sheet = 'Транзакции по заказам и товарам'
    # res = lib.read_xlsx_to_dict_v2('86.xlsx', header_row=9, values_row=11, sub_header_row=10, sheets=[sheet], exclude_nons=True)
    # res = lib.read_xlsx_to_dict_v3('temp.xlsx', 'Услуги и маржа по заказам', 8)
    # res = lib.clear_dict_keys(res.get(sheet, []))
    # print(str(res).encode('cp1251', 'ignore').decode('cp1251'))
    # sys.exit()

    # print(ya.get_shelf_report(ya.YANDEX_HEADERS, 3991087, '2024-11-01', '2025-01-31', type='SHOWS'))
    # sys.exit()
    # orders = ya.get_prices_un(ya.YANDEX_HEADERS, 22157851, '2024-11-01')
    # orders = ya.get_allorders_report_un(ya.YANDEX_HEADERS, 768444, '2024-11-01', '2024-12-01')
    # print(str(orders).encode('cp1251', 'ignore').decode('cp1251'))
    # print(orders)
    # for order in orders:
    #     print(str(order).encode('cp1251', 'ignore').decode('cp1251'))
    # sys.exit()
    # {'reportId': 'a55efe69-6a38-4200-ba36-5bf8eb92a8c9', 'estimatedGenerationTime': 10000}
    ####################################################################################################################

    excels_set = set()

    db = Database(PSQL_DATABASE, PSQL_USER, PSQL_PASW, PSQL_HOST, PSQL_PORT)
    if not db.conn:
        logging.warning("DB connection error - FINISH")
        notify_error(script_file_name, "DB connection error")
        release_lock()
        sys.exit()

    for account in ACCOUNTS:
        client_id = str(account.get('client_id', ''))
        if not client_id or client_id == 'None':
            continue
        if TEST_MODE and client_id not in TEST_CLIENTS:
            continue

        business_id = account['business_id']
        account_name = account.get('name', '')
        status_flag = account.get('status', '')
        logging.info(f"Process account {account_name} - {client_id}")

        cache = dict()
        for entity in ENTITIES:
            table = entity.get('table')
            que_str = entity.get('que', '')
            if arg_str and que_str != arg_str:
                logging.info(f"Table {table}, que {que_str} - skip")
                continue

            logging.info(f'PROCESS table - {table}')
            if not table:
                continue

            if TEST_MODE and table not in TEST_TABLES:
                continue

            func = entity.get('func')
            index_fields = entity.get('index_fields', [])
            if not index_fields:
                index_fields = ['id']
            norm_index_fields = [lib.camel_to_snake(index_field) for index_field in index_fields]
            agregate_index_field = '_'.join(norm_index_fields)
            agregate_index_fields = [agregate_index_field]
            agregate_index_field_set = set()

            ######################################### Date format for requests #########################################
            date_format = DATE_FORMAT
            datetime_format = DATETIME_FORMAT
            request_dt_format = ya.YANDEX_REQUEST_DATE_FORMAT

            last_hours = entity.get('period')
            if TEST_MODE:
                last_hours = TEST_SINCE
            elif status_flag == 'new':
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
            elif entity.get('type', '') == 'business':
                elems = entity['func'](ya.YANDEX_HEADERS, business_id, dt_since_str, dt_to_str)
                if table == 'ya_daily_prices_lk':
                    date_txt = dt_now.strftime(DATE_FORMAT)
                    for elem in elems:
                        elem['date'] = date_txt
                if entity.get('cache_key'):
                    cache[entity['cache_key']] = elems
            elif entity.get('type', '') == 'campaing':
                elems = []
                for campaign in account['campaings']:
                    butch = entity['func'](ya.YANDEX_HEADERS, campaign['id'], dt_since_str, dt_to_str)
                    logging.info(f"Recieved {len(butch)} items for campaign {campaign} for {table} from {dt_since_str} to {dt_to_str}")
                    if table in ('ya_prices', 'ya_daily_prices'):
                        for elem in butch:
                            elem['campaign_id'] = campaign['id']
                    elems.extend(butch)
                if table == 'ya_daily_prices':
                    date_txt = dt_now.strftime(DATE_FORMAT)
                    for elem in elems:
                        elem['date'] = date_txt
                if entity.get('cache_key'):
                    cache[entity['cache_key']] = elems
            elif entity.get('type', '') == 'excel':
                excel_group = entity.get('excel_group', '')
                excel_file_name = f"{client_id}_{excel_group}.xlsx"
                if excel_file_name not in excels_set:
                    if excel_group == 'allorders':
                        file_url = ya.get_allorders_report(ya.YANDEX_HEADERS, business_id, dt_since_str, dt_to_str)
                    elif excel_group == 'marketplace_services':
                        file_url = ya.get_marketplace_services_report(ya.YANDEX_HEADERS, business_id, dt_since_str, dt_to_str)
                    else:
                        file_url = None
                    if file_url and lib.get_file(file_url, excel_file_name):
                        excels_set.add(excel_file_name)
                    else:
                        logging.warning("Error download excel report")
                        continue
                excel_fields = entity.get('excel_fields')
                excel_sheet = entity.get('excel_sheet', '')
                values_row = entity.get('excel_values_row', 1)
                if excel_fields:
                    elems = get_elems_from_xlsx(excel_file_name, excel_sheet, excel_fields, values_row)
                else:
                    raw_elems = lib.read_xlsx_to_dict_v2(excel_file_name,
                                                         header_row=entity.get('excel_header_row', 1),
                                                         values_row=values_row,
                                                         sub_header_row=entity.get('excel_sub_header_row'),
                                                        sheets=[excel_sheet], exclude_nons=True)
                    elems = lib.clear_dict_keys(raw_elems.get(excel_sheet, []))
            elif entity.get('type', '') == 'zip':
                zip_dir = os.path.join(DIR_DATA, str(client_id))
                Path(zip_dir).mkdir(parents=True, exist_ok=True)
                zip_file_name = f"{client_id}_{table}.zip"
                elems = []
                if table == 'ya_boost':
                    delta_days = (datetime.datetime.strptime(dt_to_str, request_dt_format) - datetime.datetime.strptime(dt_since_str, request_dt_format)).days
                    for day in range(delta_days):
                        dt_str = (datetime.datetime.strptime(dt_to_str, request_dt_format) - datetime.timedelta(days=day)).strftime(request_dt_format)
                        file_url = ya.get_boost_report(ya.YANDEX_HEADERS, business_id, dt_str, dt_str)
                        download_res = None
                        if file_url:
                            download_res = lib.get_file(file_url, zip_file_name)
                        if not download_res:
                            logging.warning(f"Error download {file_url}")
                            continue

                        lib.unzip_files(zip_file_name, zip_dir)
                        target_file = entity.get('zip_file', 'temp.json')
                        json_file_name = os.path.join(zip_dir, target_file)

                        res_dict = lib.read_json(json_file_name)
                        batch_elems = res_dict.get('rows', [])
                        for elem in batch_elems:
                            elem['date'] = dt_str
                        elems.extend(batch_elems)
                elif table == 'ya_shelf':
                    file_url = ya.get_shelf_report(ya.YANDEX_HEADERS, business_id, dt_since_str, dt_to_str)
                    download_res = None
                    if file_url:
                        download_res = lib.get_file(file_url, zip_file_name)
                    if not download_res:
                        logging.warning(f"Error download {file_url}")
                        continue
                    lib.unzip_files(zip_file_name, zip_dir)
                    target_file = entity.get('zip_file', 'temp.json')
                    json_file_name = os.path.join(zip_dir, target_file)

                    res_dict = lib.read_json(json_file_name)
                    batch_elems = res_dict.get('rows', [])
                    elems.extend(batch_elems)

            else:
                logging.warning(f"Error inentity.get('type', '')")
                continue

            logging.info(f"Recieved {len(elems)} items from API for {table} from {dt_since_str} to {dt_to_str}")

            # for elem in elems:
            #     logging.info(elem)
            # sys.exit()

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
                lib.normalize_dict(elem, flat_dict, '', skip_fields=entity.get('skip_fields'), date_format=date_format, datetime_format=datetime_format)
                if agregate_index_field not in flat_dict:
                    flat_dict[agregate_index_field] = '_'.join([str(flat_dict.get(index_key)) for index_key in norm_index_fields])
                agregate_index_field_set.add(flat_dict[agregate_index_field])

                if flag:
                    init_template_fields_dict = lib.make_pg_dict_template(flat_dict)
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
                            if len(field) >= 64 and field[:63] in list(template_fields_dict.keys()): #FIXME new 24/04
                                continue
                            field_type = lib.recoginze_pg_value_type(flat_dict[field])
                            if db.add_table_column(table, field, field_type):
                                template_fields_dict[field] = field_type
                            else:
                                add_flag = False
                                logging.warning(f"Error add_table_column")
                                # break #FIXME 23/03
                else:
                    fields_dict = lib.make_pg_dict_template(flat_dict)
                    fields_diff = fields_dict.keys() - template_fields_dict.keys()
                    if fields_diff:
                        for field in fields_diff:
                            if len(field) >= 64 and field[:63] in list(template_fields_dict.keys()): #FIXME new 24/04
                                continue
                            field_type = lib.recoginze_pg_value_type(flat_dict[field])
                            if db.add_table_column(table, field, field_type):
                                template_fields_dict[field] = field_type
                            else:
                                add_flag = False
                                logging.warning(f"Error add_table_column")
                                # break #FIXME 23/03

                if not add_flag:
                    add_flag = True
                    logging.warning(f"Error add_flag")
                    err += 1
                    # continue #FIXME 23/03 - все равно пытаюсь добавить запись тк ошибка - column "..." of relation "ya_transactions_v2" already exists

                # flat_dict = lib.validate_values_types(flat_dict, template_fields_dict)

                if db.insert_update_item_v2(table, flat_dict, agregate_index_fields):
                    i += 1
                else:
                    err += 1
            logging.info(f"Totaly insert/update {i} (errors {err}) in table {table}")
            logging.info(f"Totaly {len(agregate_index_field_set)} uniq index values in table {table}")
        logging.info('-'*100)

    db.close()
    release_lock()
    logging.info('FINISH')
    notify_success(script_file_name)
    sys.exit()
