import asyncio
import random
import re
import time

import aiohttp
import lxml.html
import ujson

import app.common.shops.urls.speedler as speedler_data
import app.database_functions as database_functions
import app.scripts.stock.database_handler as database_handler
import app.shared.auxiliary.inputs as auxiliary_inputs
import app.shared.auxiliary.requests_handler as requests_handler
import app.shared.error_messages as error
import app.shared.valid_messages as valid
from app.shared.auxiliary.functions import parse_number

SHOP = "Speedler"

HEADERS = {
    "Host": "www.speedler.es",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "es-ES,es;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    # "Content-Length": "789",
    "Origin": "https://www.speedler.es",
    "DNT": "1",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Sec-GPC": "1",
}

BODY = {
    "options[search]": "",
    "options[key]": "category",
    "options[view]": "v_list_grid",
    "options[type]": "category",
    "options[value]": "732",
    "options[params]": "732",
    "options[show_pagination]": "true",
    "options[show_filters]": "true",
    "options[per_page]": "500",
    "options[forced_per_page]": "true",
    "options[default_per_page]": "40",
    "options[autoreset]": "true",
    "options[columns]": "3",
    "page[url]": "https://www.speedler.es/es/c/tarjetas-graficas/732",
    "o": "",
    "d": "",
    "price": "",
    "url": "https://www.speedler.es/es/c/tarjetas-graficas/732",
    "options[view_filters][JSformAttributesFilter]": "product_list/filters/verticalFilters",
    "options[view_filters][JSwrapOrderProducts]": "product_list/filters/order/order",
    "options[view_filters][JSfiltersSelecteds]": "product_list/filters/selecteds",
}

URL = "https://www.speedler.es/ajax/product_list"


async def scrape_data(logger, response, category):
    shop_id = 17
    speedler_db_data = database_functions.perform_select_availabilities(
        search_params={"shop_id": shop_id}, select_params={"code"}, distinct=True, as_dict=True, data_askey=True, key="code"
    )

    update_products = []

    products = response.xpath("//div[@class='JS_product prod prodGrid2']")
    for product in products:
        code = product.xpath("./@sku")
        if not code:
            logger.warning(error.CODE_NOT_FOUND)
            continue
        code = int(parse_number(code[0]))

        price = product.xpath("./@price")
        if not price:
            logger.warning(error.PRODUCT_PRICE_NOT_FOUND)
            continue
        price = parse_number(price[0])

        stock = product.xpath(".//div[@class='side-loader']//span//text()")
        if stock:
            stock = True if stock[0] == "En stock" or stock[0] == "Últimas unidades" else False
        else:
            stock = False

        name = product.xpath("./@name")
        if not name:
            logger.warning(error.PRODUCT_NAME_NOT_FOUND)
            continue
        name = auxiliary_inputs.fix_name(name[0])

        url = product.xpath(".//a[@class='JSproductName name']/@href")
        if not url:
            logger.warning(error.URL_NOT_FOUND)
            continue
        url = url[0]

        json_product = {"url": url, "name": name, "code": code, "price": price, "stock": stock, "category": category}
        shop_data = {"shop_name": SHOP, "shop_db_data": speedler_db_data, "shop_id": shop_id}
        result, product_tuple = database_handler.add_product(logger, shop_data, json_product)
        if result == False:
            continue
        update_products.append(product_tuple)
        continue

    return update_products


async def download_data(logger, session, url, category):
    response = await requests_handler.post(logger, session, url, data=BODY, headers=HEADERS)
    if not response:
        return False

    try:
        response = ujson.loads(response)
    except:
        logger.error(error.parse_json(url))
        return False

    try:
        response = lxml.html.fromstring(response.get("list", ""))
    except:
        logger.error(error.parse_html(url))
        return False

    return await scrape_data(logger, response, category)


async def main(logger, category_selected=[]):
    try:
        conn = aiohttp.TCPConnector(limit=60)
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(connector=conn, timeout=timeout, headers=HEADERS) as session:
            for category in speedler_data.urls:
                if len(category_selected) > 0 and category not in category_selected:
                    continue
                elif (category == "GPU" or category == "CPU") and len(category_selected) == 0:
                    continue

                url = speedler_data.urls[category].get("url", "")
                category_code = re.findall("\d+", url, re.IGNORECASE)[0]

                BODY["url"] = url
                BODY["page[url]"] = url
                BODY["options[value]"] = category_code
                BODY["options[params]"] = category_code

                # HEADERS["Content-Length"] = speedler_data.urls[category].get("Content-Length", "")
                update_products = await download_data(logger, session, URL, category)
                database_handler.process_data(logger, update_products)

                wait_time = random.randint(500, 3000) / 1000
                time.sleep(wait_time)

    except asyncio.exceptions.TimeoutError:
        logger.error(error.TIMEOUT_ERROR)
