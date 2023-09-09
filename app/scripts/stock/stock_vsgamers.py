import random
import time

import aiohttp
import lxml.html
import ujson

import app.common.shops.urls.vsgamers as vsgamers_data
import app.database_functions as database_functions
import app.scripts.stock.database_handler as database_handler
import app.shared.auxiliary.inputs as auxiliary_inputs
import app.shared.auxiliary.requests_handler as requests_handler
import app.shared.error_messages as error
import app.shared.regex.product as regex_product
import app.shared.valid_messages as valid
from app.shared.auxiliary.functions import parse_number

SHOP = "Versus Gamers"
WEB = "https://www.vsgamers.es"

HEADERS = {
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "es-ES,es;q=0.8",
    "Accept": "*/*",
    "Connection": "keep-alive",
    "Host": "www.vsgamers.es",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:103.0) Gecko/20100101 Firefox/103.0",
}


async def scrape_data(logger, response, category):
    shop_id = 12
    vsgamers_db_data = database_functions.perform_select_availabilities(
        search_params={"shop_id": shop_id}, select_params={"code"}, distinct=True, as_dict=True, data_askey=True, key="code"
    )

    elements = response.xpath("(//div[@class='vs-product-card'])")
    update_products = []

    contador = 0
    for element in elements:
        try:
            product = element.xpath("(./@data-info)")[0]
            product = ujson.loads(product)
            contador += 1
        except:
            logger.warning(error.JSON_ERROR)
            contador += 1
            continue

        code = int(product.get("id", None))
        if not code:
            logger.warning(f"Sin code {code}")
            continue

        price = element.xpath("(.//span[@class='vs-product-card-prices-price'])/@data-price")
        if not price:
            logger.warning(f"Sin precio {code - {price}}")
            continue

        price = parse_number(round(float(price[0]), 2))

        stock = True if element.xpath("(.//button[@type='button'])") else False

        url = element.xpath("(.//div[@class='vs-product-card-title']//a/@href)")
        if not url:
            logger.warning(error.URL_NOT_FOUND)
            continue
        url = WEB + url[0]

        name = product.get("name", None)
        if not name:
            logger.warning(error.PRODUCT_NAME_NOT_FOUND)
            continue

        second_name = element.xpath("(.//div[@class='vs-product-card-title']//a/@title)")
        if second_name:
            second_name = second_name[0]
        else:
            second_name = None

        category = regex_product.validate_category(category)
        if not category:
            continue

        part_number = product.get("sku", None)
        manufacturer = product.get("brand", None)

        json_product = {
            "url": url,
            "name": name,
            "code": code,
            "price": price,
            "stock": stock,
            "category": category,
            "manufacturer": manufacturer,
            "second_name": second_name,
            "part_number": part_number,
        }
        shop_data = {"shop_name": SHOP, "shop_db_data": vsgamers_db_data, "shop_id": shop_id}

        if category == "CPU Cooler" or category == "Chassis":
            result, product_tuple = database_handler.add_product(logger, shop_data, json_product)
        else:
            result, product_tuple = database_handler.add_product(logger, shop_data, json_product, process_flag=False)

        if result == False:
            continue
        update_products.append(product_tuple)
        continue

    return update_products


async def download_data(logger, session, url, category, proxy=None):
    response = await requests_handler.get(logger, session, url)
    if not response:
        return False

    try:
        response = lxml.html.fromstring(response)
    except:
        logger.error(error.parse_html(url))
        return False

    return await scrape_data(logger, response, category)


async def main(logger, category_selected=[]):
    conn = aiohttp.TCPConnector(limit=15)
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(connector=conn, timeout=timeout, headers=HEADERS) as session:
        for category in vsgamers_data.urls:
            if len(category_selected) > 0 and category not in category_selected:
                continue
            elif (category == "GPU" or category == "CPU") and len(category_selected) == 0:
                continue

            url = vsgamers_data.urls[category]
            update_products = await download_data(logger, session, url, category)
            logger.info(valid.url_successful(url))

            database_handler.process_data(logger, update_products)

            wait_time = random.randint(500, 3000) / 1000
            time.sleep(wait_time)
