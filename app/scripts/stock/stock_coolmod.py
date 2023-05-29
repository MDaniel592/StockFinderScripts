import asyncio
import random
import time

import aiohttp
import lxml.html

import app.common.shops.urls.coolmod as coolmod_data
import app.database_functions as database_functions
import app.scripts.stock.database_handler as database_handler
import app.shared.auxiliary.inputs as auxiliary_inputs
import app.shared.auxiliary.requests_handler as requests_handler
import app.shared.error_messages as error
import app.shared.valid_messages as valid
from app.shared.auxiliary.functions import parse_number
from app.shared.environment_variables import PersonalProxy

SHOP = "Coolmod"
WEB = "https://www.coolmod.com"

HEADERS = {
    "Host": "www.coolmod.com",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:103.0) Gecko/20100101 Firefox/103.0",
    "Accept": "*/*",
    "Accept-Language": "es-ES,es;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.coolmod.com/",
    "Origin": "https://www.coolmod.com",
    "DNT": "1",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
    "Sec-GPC": "1",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
}


async def scrape_data(logger, response, category):
    shop_id = 3
    coolmod_db_data = database_functions.perform_select_availabilities(
        search_params={"shop_id": shop_id}, select_params={"code"}, distinct=True, as_dict=True, data_askey=True, key="code"
    )

    products = response.xpath("//div[contains(@class,'productInfo')]")
    update_products = []

    for product in products:
        code = product.xpath("./@id")
        if not code:
            logger.warning(error.CODE_NOT_FOUND)
            continue
        code = int(parse_number(code[0].replace("productPROD-", "")))

        price = product.xpath("./@data-price")
        if not price:
            logger.warning(error.PRODUCT_PRICE_NOT_FOUND)
            continue
        price = parse_number(price[0])

        stock = product.xpath("(.//span[@class='stock on'])")
        stock = True if stock else False

        name = product.xpath(".//div[@class='productName']//div//div//a//text()")
        if not name:
            logger.warning(error.PRODUCT_NAME_NOT_FOUND)
            continue

        refurbished = False
        if category == "Reaco":
            category = name[0].split("-")
            category = category[len(category) - 1]
            category = auxiliary_inputs.fix_name_chars(category)
            refurbished = True

        name = auxiliary_inputs.fix_name(name[0])

        url = product.xpath(".//div[@class='productName']//div//div//a/@href")
        if not url:
            logger.warning(error.URL_NOT_FOUND)
            continue
        url = WEB + url[0]

        json_product = {"url": url, "name": name, "code": code, "price": price, "stock": stock, "category": category, "refurbished": refurbished}
        shop_data = {"shop_name": SHOP, "shop_db_data": coolmod_db_data, "shop_id": shop_id}
        result, product_tuple = database_handler.add_product(logger, shop_data, json_product)
        if result == False:
            continue
        update_products.append(product_tuple)
        continue

    return update_products


async def main(logger, category_selected=[]):
    try:
        conn = aiohttp.TCPConnector(limit=15)
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(connector=conn, timeout=timeout, headers=HEADERS) as session:
            for category in coolmod_data.urls:
                if len(category_selected) > 0 and category not in category_selected:
                    continue
                elif (category == "GPU" or category == "CPU" or category == "Reaco") and len(category_selected) == 0:
                    continue

                url = coolmod_data.urls[category]
                response = await requests_handler.get(logger, session, url, proxy=PersonalProxy)
                if not response:
                    continue

                try:
                    response = lxml.html.fromstring(response)
                except:
                    logger.error(error.parse_html(url))
                    continue

                update_products = await scrape_data(logger, response, category)
                database_handler.process_data(logger, update_products)

                wait_time = random.randint(500, 3000) / 1000
                time.sleep(wait_time)

    except asyncio.exceptions.TimeoutError:
        logger.error(error.TIMEOUT_ERROR)
