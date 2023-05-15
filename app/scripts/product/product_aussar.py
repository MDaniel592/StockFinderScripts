import asyncio
import random

import aiohttp
import lxml.html
import ujson

import app.utils.error_messages as error
import app.utils.product_regex as product_regex
import app.utils.requests_handler as requests_handler
import app.utils.shops.regex.aussar as aussar_aux_functions
import app.utils.valid_messages as valid
from app.utils.aux_functions import download_save_images, parse_number
from app.utils.shared_variables import IMAGE_BASE_DIR, KubernetesProxyList

HEADERS = {
    "Accept-Encoding": "gzip, deflate",
    "Accept": "*/*",
    "Connection": "keep-alive",
}


SHOP = "Aussar"
IMAGE_SHOP_DIR = f"{IMAGE_BASE_DIR}/{SHOP.lower()}"


async def process_product(logger, session, product, response):

    code = product.get("code", 0)
    url = product.get("url", None)
    name = product.get("name", None)
    part_number = product.get("sku", None)
    category = product.get("category", None)
    manufacturer = product.get("brand", {}).get("name", None)
    price = parse_number(product.get("offers", {}).get("price", -1))
    stock = True if product.get("offers", {}).get("availability", "").find("InStock") != -1 else False

    medium_image = product.get("image", None)
    large_images = product.get("offers", {}).get("image", None)

    product = {
        "url": url,
        "name": name,
        "code": code,
        "price": price,
        "stock": stock,
        "category": category,
        "part_number": part_number,
        "manufacturer": manufacturer,
    }
    logger.info(f"medium_image: {medium_image} - large_images: {large_images}")
    logger.info(product)
    category = product_regex.validate_category(category)
    if not category:
        product["error_message"] = error.CATEGORY_NOT_FOUND
        product["error"] = True
        return product
    product["category"] = category

    new_product = aussar_aux_functions.scrape_category(response, product, category)
    if not new_product:
        product["error_message"] = error.SPECS_NOT_FOUND
        product["error"] = True
        return product
    product = new_product

    images = {}
    if medium_image:
        image_size = "medium"
        medium_image = await download_save_images(session, [medium_image], part_number, code, image_size, IMAGE_SHOP_DIR)
        if medium_image == "Ya exiten":
            pass
        if medium_image:
            images["medium"] = medium_image

    if large_images:
        image_size = "large"
        large_image = await download_save_images(session, large_images, part_number, code, image_size, IMAGE_SHOP_DIR, check=False)
        if large_image == "Ya exiten":
            pass
        if large_image:
            images["large"] = large_image

    # if not images:
    #     pass

    result = product_regex.process_product(product, SHOP, 0)
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

    product_data_code = response.cssselect("#product-details")
    product_data = response.cssselect("html>head>script:nth-of-type(4)")
    if not product_data:
        return False, error.PRODUCT_DATA_NOT_FOUND

    try:
        product_data_code = product_data_code[0].get("data-product")
        product_data_code = ujson.loads(product_data_code)
        product_data = ujson.loads(product_data[0].text_content())
    except:
        return False, error.JSON_ERROR

    product_code = product_data_code.get("id", -1)
    if product_code == -1:
        return False, error.CODE_NOT_FOUND

    product_data["code"] = product_code
    product_data["url"] = url
    return product_data, response


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

                shop_data[entry]["result"] = await process_product(logger, session, product_data, response)

    except asyncio.exceptions.TimeoutError:
        logger.error(error.TIMEOUT_ERROR)
        return []

    return shop_data
