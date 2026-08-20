# -- coding: utf-8 --
"""
Postgre lib, psql lib
Автор: Олег Шабалов
Контакты: 89179021656, @olegshabalov
"""

import logging
import datetime

import psycopg2


class Database:
    def __init__(self, dbname, user, password, host, port):
        try:
            self.conn = psycopg2.connect(dbname=dbname, user=user,
                                    password=password, host=host, port=port)
            self.cursor = self.conn.cursor()
        except Exception as e:
            logging.warning(str(e))
            self.conn = None
            self.cursor = None
        self.dbname = dbname
        self.user = user
        self.password = password
        self.host = host
        self.port = port


    def test(self):
        try:
            self.cursor.execute("SELECT version()")
            self.cursor.fetchone()
        except:
            return False
        return True


    def reconnect(self):
        try:
            self.conn = psycopg2.connect(dbname=self.dbname, user=self.user,
                                    password=self.password, host=self.host, port=self.port)
            self.cursor = self.conn.cursor()
        except Exception as e:
            logging.warning(str(e))
            self.conn = None
            self.cursor = None


    def flush(self):
        try:
            self.cursor.execute("ROLLBACK")
            self.conn.commit()
        except:
            return False
        return True


    def create_table_from_dict_template(self, table: str, dict_template: dict[str, str], index_fields: list = None):
        fields_text = ''
        for key in dict_template:
            fields_text += f'{key} {dict_template[key]},'

        if not index_fields:
            index_fields = ['uuid']
            fields_text += f'{index_fields[0]} SERIAL,'

        index_fields_text = ','.join(index_fields)

        sql_request = f"CREATE TABLE IF NOT EXISTS {table} ({fields_text} PRIMARY KEY ({index_fields_text}))"

        try:
            self.cursor.execute(sql_request)
            self.conn.commit()
        except Exception as e:
            logging.warning(sql_request)
            logging.warning(str(e))
            self.flush()
            return None
        return index_fields


    def add_table_column(self, table: str, field: str, type: str):
        sql_request = f"ALTER TABLE {table} ADD COLUMN {field} {type}"
        try:
            self.cursor.execute(sql_request)
            self.conn.commit()
        except Exception as e:
            logging.warning(sql_request)
            logging.warning(str(e))
            self.flush()
            return False
        return True


    def get_fields_dict(self, table: str):
        sql_request = f"SELECT column_name, data_type from INFORMATION_SCHEMA.COLUMNS where table_name = '{table}'"
        res = dict()
        try:
            self.cursor.execute(sql_request)
            raw_list = self.cursor.fetchall()
        except Exception as e:
            logging.warning(sql_request)
            logging.warning(str(e))
            return res
        for elem in raw_list:
            res[elem[0]] = elem[1]
        return res


    def insert_update_item(self, table: str, flat_product_dict: dict, index_fields: list):
        fields_text = ''
        values_text = ''
        equals_text = ''
        for key in flat_product_dict:
            fields_text += f"{key},"
            if isinstance(flat_product_dict[key], str):
                flat_product_dict[key] = flat_product_dict[key].replace("'", '"')
                values_text += f"'{flat_product_dict[key]}',"
                equals_text += f"{key}='{flat_product_dict[key]}',"
            elif isinstance(flat_product_dict[key], datetime.datetime):
                values_text += f"'{flat_product_dict[key]}',"
                equals_text += f"{key}='{flat_product_dict[key]}',"
            else:
                values_text += f"{flat_product_dict[key]},"
                equals_text += f"{key}={flat_product_dict[key]},"
        fields_text = fields_text[:-1]
        values_text = values_text[:-1]
        equals_text = equals_text[:-1]
        index_fields_text = ','.join(index_fields)

        sql_request = f"INSERT INTO {table} ({fields_text}) VALUES ({values_text}) ON CONFLICT ({index_fields_text}) DO UPDATE SET {equals_text}"

        try:
            self.cursor.execute(sql_request)
            self.conn.commit()
        except Exception as e:
            logging.warning(sql_request)
            logging.warning(str(e))
            self.flush()
            return False
        return True

    def insert_update_item_v2(self, table: str, flat_product_dict: dict, index_fields: list):
        fields_text = ''
        values_text = ''
        equals_text = ''
        for key in flat_product_dict:
            if not flat_product_dict[key]:
                continue
            fields_text += f"{key},"
            if isinstance(flat_product_dict[key], str):
                flat_product_dict[key] = flat_product_dict[key].replace("'", '"')
                values_text += f"'{flat_product_dict[key]}',"
                equals_text += f"{key}='{flat_product_dict[key]}',"
            elif isinstance(flat_product_dict[key], datetime.datetime):
                values_text += f"'{flat_product_dict[key]}',"
                equals_text += f"{key}='{flat_product_dict[key]}',"
            else:
                values_text += f"{flat_product_dict[key]},"
                equals_text += f"{key}={flat_product_dict[key]},"
        fields_text = fields_text[:-1]
        values_text = values_text[:-1]
        equals_text = equals_text[:-1]
        index_fields_text = ','.join(index_fields)

        sql_request = f"INSERT INTO {table} ({fields_text}) VALUES ({values_text}) ON CONFLICT ({index_fields_text}) DO UPDATE SET {equals_text}"

        try:
            self.cursor.execute(sql_request)
            self.conn.commit()
        except Exception as e:
            logging.warning(sql_request)
            logging.warning(str(e))
            self.flush()
            return False
        return True

    def read_query(self, query: str):
        try:
            self.cursor.execute(query)
            raw_list = self.cursor.fetchall()
        except Exception as e:
            logging.warning(query)
            logging.warning(str(e))
            return []
        return raw_list

    def write_query(self, query: str):
        try:
            self.cursor.execute(query)
            self.conn.commit()
        except Exception as e:
            logging.warning(query)
            logging.warning(str(e))
            self.flush()
            return False
        return True

    def setAutoCommit(self, flag: bool):
        try:
            self.conn.autocommit = flag
        except Exception as e:
            logging.warning(str(e))
            self.flush()
            return False
        return True

    def close(self):
        self.cursor.close()