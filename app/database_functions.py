import logging
import os
import socket
import sys

import psycopg2
import psycopg2.extras
from psycopg2 import Error
from psycopg2.extras import execute_values

import app.shared.error_messages as error_messages
import app.shared.valid_messages as valid_messages

logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)
logger.propagate = False

HOSTNAME = os.environ.get("HOSTNAME", False)
DATABASE = os.environ.get("POSGRESQL_DATABASE")

LOCAL_USER = os.environ.get("POSGRESQL_LOCAL_USER")
LOCAL_USER_PASSWORD = os.environ.get("POSGRESQL_LOCAL_USER_PASSWORD")
LOCAL_URL = os.environ.get("POSGRESQL_LOCAL_URL")
LOCAL_PORT = os.environ.get("POSGRESQL_LOCAL_PORT")

REMOTE_USER = os.environ.get("POSGRESQL_REMOTE_USER")
REMOTE_USER_PASSWORD = os.environ.get("POSGRESQL_REMOTE_USER_PASSWORD")
REMOTE_URL = os.environ.get("POSGRESQL_REMOTE_URL")
REMOTE_PORT = os.environ.get("POSGRESQL_REMOTE_PORT")


def sql_connection():

    if HOSTNAME == "Docker":
        # Localhost / Docker
        connection = psycopg2.connect(user=LOCAL_USER, password=LOCAL_USER_PASSWORD, host=LOCAL_URL, port=LOCAL_PORT, database=DATABASE)
    else:
        # Remote Host
        connection = psycopg2.connect(user=REMOTE_USER, password=REMOTE_USER_PASSWORD, host=REMOTE_URL, port=REMOTE_PORT, database=DATABASE)

    return connection


def update_multiple_row_availabilities(columns, values, equal_params):
    connection = sql_connection()
    if connection is None:
        return False

    update_values = ""
    data_str = ""
    for column in columns:
        if column in equal_params:
            data_str += column + ","
            continue

        update_values += f"{column} = data.{column}, "
        data_str += column + ","

    equal_str = ""
    for index in range(len(equal_params)):
        equal_str += f"products_availabilities.{equal_params[index]} = data.{equal_params[index]}"
        if index + 1 != len(equal_params):
            equal_str += " AND "

    update_values = update_values[:-2]
    data_str = data_str[:-1]

    cursor = connection.cursor()
    query = f"UPDATE products_availabilities SET {update_values} FROM (VALUES %s) AS data ({data_str}) WHERE {equal_str}"

    try:
        execute_values(cursor, query, values)
        connection.commit()
        logger.info(valid_messages.db_success(sys._getframe().f_code.co_name, "products_availabilities"))
        cursor.close()
        connection.close()
        return True
    except Error as err:
        logger.warning(error_messages.db_error(sys._getframe().f_code.co_name, "products_availabilities", err))
        cursor.close()
        connection.close()
        return False


def perform_select_availabilities(select_params, search_params, operator="AND", distinct=False, as_dict=False, data_askey=False, data_list=False, key=None):
    connection = sql_connection()
    if data_askey:
        data = {}
    else:
        data = []
    if connection is None:
        return data
    search_params_list = list(search_params.keys())
    search_params_values_list = list(search_params.values())

    where_clause = f"{search_params_list[0]} = '{search_params_values_list[0]}'"
    contador = 1
    for search_param in search_params_list[1:]:
        where_clause = where_clause + f" {operator} " + f"{search_param} = '{search_params_values_list[contador]}'"
        contador += 1
    select_clause = ",".join(select_params)
    if distinct:
        distinct = "distinct"
    else:
        distinct = ""

    try:
        with connection:
            if as_dict:
                cursor = connection.cursor(cursor_factory=psycopg2.extras.DictCursor)
            else:
                cursor = connection.cursor()
            cursor.execute(f"SELECT {distinct} {select_clause} FROM products_availabilities WHERE {where_clause}")
            cursor = cursor.fetchall()
            if as_dict:
                for row in cursor:
                    if data_askey:
                        if not key:
                            raise Error

                        row_dict = dict(row)
                        key_value = row_dict[key]
                        row_dict.pop(key, None)
                        data[key_value] = row_dict if row_dict else True

                    else:
                        data.append(dict(row))
            elif data_list:
                for row in cursor:
                    data.append(row[0])
            else:
                data = cursor

        connection.close()
        logger.info(valid_messages.db_success(sys._getframe().f_code.co_name, "products_availabilities"))
        return data
    except Error as err:
        logger.warning(error_messages.db_error(sys._getframe().f_code.co_name, "products_availabilities", err))
        connection.close()
        return data


def get_availabilities_stock_time(shop_id, in_stock=0, distinct=True, tiempo=5, limit="NULL"):
    connection = sql_connection()
    data = []
    if connection is None:
        return data

    if distinct:
        distinct = "distinct"
    else:
        distinct = ""

    cursor = connection.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        with connection:
            cursor.execute(
                f"SELECT {distinct} url, url_code FROM products_availabilities pu WHERE pu.shop_id = '{shop_id}' AND pu.in_stock = '{in_stock}' AND pu.updated_at < NOW() - INTERVAL '{tiempo} minutes' LIMIT {limit}"
            )
            cursor = cursor.fetchall()
            for row in cursor:
                data.append(dict(row))

        logger.info(valid_messages.db_success(sys._getframe().f_code.co_name, "products_availabilities"))
        connection.close()
        return data
    except Error as err:
        logger.warning(error_messages.db_error(sys._getframe().f_code.co_name, "products_availabilities", err))
        connection.close()
        return []
