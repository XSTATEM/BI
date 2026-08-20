# -- coding: utf-8 --
"""
Автор: Олег Шабалов
Контакты: 89179021656, @olegshabalov
"""


LOCAL_MODE = 0

if LOCAL_MODE:
    DIR_SCRIPT = ''
    DIR_DATA = ''
else:
    DIR_SCRIPT = '/home/user/script'
    DIR_DATA = '/home/user/script'

ACCOUNTS_XLSX_FILE = 'accounts.xlsx' #in DIR_DATA
TRY = 3
SLEEP_TIME = 5
SLEEP_TIME_REPORT = 61
SLEEP_TIME_ANALYTICS = 21
MAX_STR_SIZE = 255

####################################################### PSQL ###########################################################
PSQL_HOST = "78.29.32.200" if LOCAL_MODE else "78.29.32.200"
PSQL_USER = "root"
PSQL_PASW = "eXA94KJDgke4{m4h"
PSQL_DATABASE = "mpdb"
PSQL_PORT = 5432

###################################################### WB ##############################################################
WB_PAGINATION_LIMIT = 500
WB_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
WB_DATE_FORMAT = "%Y-%m-%d"

###################################################### MS ##############################################################
MS_DATE_FROMAT = "%Y-%m-%d %H:%M:%S"
MS_SUPPLYS_DAYS = 14 #FIXME 14
MS_SUPPLYS_DAYS_NEW_CLIENT = 180



