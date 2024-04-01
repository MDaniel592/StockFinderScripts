import asyncio
import random
import re
import time

import aiohttp
import lxml.html

import app.common.shops.urls.izarmicro as izarmicro_data
import app.database_functions as database_functions
import app.scripts.stock.database_handler as database_handler
import app.shared.auxiliary.inputs as auxiliary_inputs
import app.shared.auxiliary.requests_handler as requests_handler
import app.shared.error_messages as error
import app.shared.valid_messages as valid
from app.shared.auxiliary.functions import parse_number

SHOP = "IzarMicro"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_20_77) AppleWebKit/531.71.18 (KHTML, like Gecko) Chrome/55.1.6997.1625 Safari/532.00 Edge/36.04460"
HEADERS = {
    "Origin": "www.izarmicro.com",
    "User-Agent": f"{USER_AGENT}",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "es-ES,es;q=0.8",
    "Accept": "*/*",
    "Connection": "keep-alive",
}


async def scrape_data(logger, response, category):
    shop_id = 4
    izarmicro_db_data = database_functions.perform_select_availabilities(
        search_params={"shop_id": shop_id}, select_params={"code"}, distinct=True, as_dict=True, data_askey=True, key="code"
    )

    products = response.xpath("(.//div[@class='divproportada2'])")
    update_products = []

    counter = 0
    for product in products:
        destacado = product.xpath(f"(.//div[@class='plist_img2'])//span[@class='destacado']/text()")
        if destacado and counter == 0:
            counter += 1
            continue

        url = product.xpath(f"(.//div[@class='plist_img2'])//a/@href")
        if not url:
            logger.warning(f"NO url {url}")
            continue
        url = url[0]

        try:
            code = re.findall("art-\d+", url, flags=re.IGNORECASE)[0]
            code = re.findall("\d+", code, flags=re.IGNORECASE)[0]
        except:
            logger.warning(f"NO code {code}")
            continue
        code = int(code)

        try:
            price = product.xpath(f"(.//div[@class='tdispo4'])//div[2]//span/text()")[0]
        except:
            logger.warning(f"NO price")
            continue
        price = auxiliary_inputs.fix_name(price)
        price = parse_number(float(price))

        stock = product.xpath(f"(.//button[@class='compra2'])/text()")
        if not stock:
            stock = False
        else:
            stock = stock[0].upper()
            stock = True if stock == "COMPRAR" else False

        name = product.xpath(f"(.//div[@class='plist_img2'])//a/text()")
        if not name:
            name = product.xpath(f"(.//div[@class='plist_img2'])//a//h2/text()")
            if not name:
                logger.warning(error.PRODUCT_NAME_NOT_FOUND)
                continue

        name = auxiliary_inputs.fix_name(name[0])

        second_name = product.xpath(f"(.//div[@class='plist_img2'])//span[@class='desport']/text()")
        if second_name:
            second_name = second_name[0]
        else:
            second_name = None

        part_number = product.xpath(f"(.//div[@class='plist_img2'])//span[@class='mpntxt']/text()")
        if part_number:
            part_number = part_number[0]
        else:
            part_number = None

        part_number = part_number[1:] if part_number[0] == " " else part_number
        part_number = part_number[:-1] if part_number[len(part_number) - 1] == " " else part_number

        json_product = {
            "url": url,
            "name": name,
            "code": code,
            "price": price,
            "stock": stock,
            "category": category,
            "part_number": part_number,
            "second_name": second_name,
        }
        shop_data = {"shop_name": SHOP, "shop_db_data": izarmicro_db_data, "shop_id": shop_id}

        if category == "CPU Cooler" or category == "Chassis":
            result, product_tuple = database_handler.add_product(logger, shop_data, json_product)
        else:
            result, product_tuple = database_handler.add_product(logger, shop_data, json_product, process_flag=False)

        if result == False:
            continue
        update_products.append(product_tuple)
        continue

    return update_products


async def main(logger, category_selected=[]):
    try:
        for category in izarmicro_data.urls:
            conn = aiohttp.TCPConnector(limit=60)
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(connector=conn, timeout=timeout, headers=HEADERS) as session:
                if len(category_selected) > 0 and category not in category_selected:
                    continue
                elif (category == "GPU" or category == "CPU") and len(category_selected) == 0:
                    continue

                update_products = []
                for data in izarmicro_data.urls[category]:
                    url = data.get("url", None)

                    response = await requests_handler.get(logger, session, url)
                    if not response:
                        continue

                    try:
                        response = lxml.html.fromstring(response)
                    except:
                        logger.error(error.parse_html(url))
                        continue

                    products_list = await scrape_data(logger, response, category)
                    if products_list:
                        update_products += products_list

            database_handler.process_data(logger, update_products)

            wait_time = random.randint(500, 3000) / 1000
            time.sleep(wait_time)

    except asyncio.exceptions.TimeoutError:
        logger.error(error.TIMEOUT_ERROR)
