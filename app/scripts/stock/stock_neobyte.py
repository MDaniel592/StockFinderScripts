import asyncio
import random
import time

import aiohttp
import ujson

import app.common.shops.urls.neobyte as neobyte_data
import app.database_functions as database_functions
import app.scripts.stock.database_handler as database_handler
import app.shared.auxiliary.inputs as auxiliary_inputs
import app.shared.auxiliary.requests_handler as requests_handler
import app.shared.error_messages as error
import app.shared.regex.product as regex_product
import app.shared.valid_messages as valid
from app.shared.auxiliary.functions import parse_number

SHOP = "Neobyte"
WEB = "https://www.neobyte.es"

HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.0",
    "Accept-Language": "es-ES,es;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Host": "www.neobyte.es",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:103.0) Gecko/20100101 Firefox/103.0",
}


async def scrape_data(logger, response, category):
    shop_id = 7
    neobyte_db_data = database_functions.perform_select_availabilities(
        search_params={"shop_id": shop_id}, select_params={"code"}, distinct=True, as_dict=True, data_askey=True, key="code"
    )

    elements = response["products"]
    update_products = []

    for element in elements:
        code = int(element.get("id_product", None))
        if not code:
            logger.warning(f"Sin code {code}")
            continue

        price = element.get("price_amount", None)
        if not price:
            logger.warning(f"Sin precio {code - {price}}")
            continue
        price = parse_number(round(float(price), 2))

        stock = True if element.get("add_to_cart_url", False) else False

        url = element.get("url", None)
        if not url:
            logger.warning(error.URL_NOT_FOUND)
            continue

        name = element.get("name", None)
        if not name:
            logger.warning(error.PRODUCT_NAME_NOT_FOUND)
            continue

        category = regex_product.validate_category(category)
        if not category:
            category = regex_product.validate_category(name, short=False)
            if not category:
                continue

        description = element.get("description_short", None)

        json_product = {"url": url, "name": name, "code": code, "price": price, "stock": stock, "category": category, "description": description}
        shop_data = {"shop_name": SHOP, "shop_db_data": neobyte_db_data, "shop_id": shop_id}
        result, product_tuple = database_handler.add_product(logger, shop_data, json_product)
        if result == False:
            continue
        update_products.append(product_tuple)
        continue

    return update_products


async def main(logger, category_selected=[]):
    try:
        conn = aiohttp.TCPConnector(limit=15)
        timeout = aiohttp.ClientTimeout(total=45)
        async with aiohttp.ClientSession(connector=conn, timeout=timeout, headers=HEADERS) as session:
            for category in neobyte_data.urls:
                if len(category_selected) > 0 and category not in category_selected:
                    continue
                elif (category == "GPU" or category == "CPU") and len(category_selected) == 0:
                    continue

                url = neobyte_data.urls[category]
                HEADERS["Referer"] = url

                response = await requests_handler.get(logger, session, url)
                if not response:
                    continue

                try:
                    response = ujson.loads(response)
                except:
                    logger.error(error.parse_html(url))
                    continue

                update_products = await scrape_data(logger, response, category)
                if not update_products:
                    continue

                database_handler.process_data(logger, update_products)

                wait_time = random.randint(500, 3000) / 1000
                time.sleep(wait_time)

    except asyncio.exceptions.TimeoutError:
        logger.error(error.TIMEOUT_ERROR)
