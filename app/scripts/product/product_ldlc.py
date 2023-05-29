import asyncio
import random
import re
import time

import aiohttp
import lxml.html
import ujson

import app.common.shops.regex.ldlc as ldlc_aux_functions
import app.shared.auxiliary.requests_handler as requests_handler
import app.shared.error_messages as error
import app.shared.regex.product as regex_product
import app.shared.valid_messages as valid
from app.shared.auxiliary.functions import download_save_images, parse_number
from app.shared.environment_variables import IMAGE_BASE_DIR, KubernetesProxyList

HEADERS = {
    "Accept-Encoding": "gzip, deflate",
    "Accept": "*/*",
    "Connection": "keep-alive",
}

SHOP = "LDLC"
IMAGE_SHOP_DIR = f"{IMAGE_BASE_DIR}/{SHOP.lower()}"


async def process_product(session, product, response):
    url = product.get("url", None)

    code = re.findall("PB\d+", url)
    code = re.findall("\d+", code[0])[0]

    name = product.get("name", None)
    images = product.get("image", None)
    part_number = product.get("mpn", None)
    category = product.get("category", None)
    manufacturer = product.get("brand", {}).get("name", None)
    price = parse_number(product.get("offers", {}).get("price", -1))
    stock = True if product.get("offers", {}).get("availability", "").find("InStock") != -1 else False
    refurbished = False if product.get("offers", {}).get("itemCondition", "").find("NewCondition") != -1 else True

    product = {
        "url": url,
        "name": name,
        "code": code,
        "price": price,
        "stock": stock,
        "category": category,
        "part_number": part_number,
        "refurbished": refurbished,
        "manufacturer": manufacturer,
    }

    category = regex_product.validate_category(category)
    if not category:
        product["error_message"] = error.CATEGORY_NOT_FOUND
        product["error"] = True
        return product
    product["category"] = category

    new_product = ldlc_aux_functions.scrape_category(response, product, category)
    if not new_product:
        product["error_message"] = error.SPECS_NOT_FOUND
        product["error"] = True
        return product
    product = new_product

    image_size = "large"
    images = await download_save_images(session, images, part_number, code, image_size, IMAGE_SHOP_DIR)
    if not images:
        product["error_message"] = error.PRODUCT_IMG_NOT_FOUND
        product["error"] = True
        return product

    result = regex_product.process_product(product, SHOP, 0)
    if not result:
        product["error_message"] = error.PRODUCT_NOT_ADDED
        product["error"] = True

    return product


async def download_data(logger, session, url, proxy):
    logger.info(f"Consultando url: {url}")

    response = await requests_handler.get(logger, session, url, proxy)
    if not response:
        return False, error.GET_NOT_COMPLETED

    try:
        response = lxml.html.fromstring(response)
    except:
        return False, error.HTML_PARSE_ERROR

    product_data = response.xpath("(//script[@type='application/ld+json'])[1]/text()")
    data_category = response.cssselect("html>head>script:nth-of-type(3)")
    if not product_data:
        return False, error.PRODUCT_DATA_NOT_FOUND

    try:
        data_category = str(data_category[0].text_content())
        data_category = data_category.split("'ecommerce': ")[1]
        data_category = data_category.split("});")[0]
        data_category = data_category.replace("'", '"')
        #
        product_data = ujson.loads(product_data[0])
        data_category = ujson.loads(data_category)
    except:
        return False, error.JSON_ERROR

    category = data_category.get("detail", {}).get("products", [{}])[0].get("category", None)
    product_data["url"] = url
    product_data["category"] = category

    return await process_product(session, product_data, response), True


async def main(logger, shop_data):
    if not shop_data:
        return False

    try:
        conn = aiohttp.TCPConnector(limit=15)
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(connector=conn, timeout=timeout, headers=HEADERS) as session:
            for entry in range(len(shop_data)):
                url = shop_data[entry]["url"]
                product_data, response = await download_data(logger, session, url, proxy=random.choice(KubernetesProxyList))
                if product_data == False:
                    shop_data[entry]["result"] = {"error": True, "error_message": response}
                    continue

                shop_data[entry]["result"] = product_data
                time.sleep(random.randint(5, 10))

    except asyncio.exceptions.TimeoutError:
        logger.error(error.TIMEOUT_ERROR)
        return []

    return shop_data
