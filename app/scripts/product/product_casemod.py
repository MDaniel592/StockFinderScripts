import asyncio
import logging
import random
import re

import aiohttp
import lxml.html
import ujson

import app.utils.error_messages as error
import app.utils.product_regex as product_regex
import app.utils.requests_handler as requests_handler
import app.utils.valid_messages as valid
from app.utils.aux_functions import download_save_images, parse_number
from app.utils.shared_variables import IMAGE_BASE_DIR, KubernetesProxyList

HEADERS = {
    "Accept-Encoding": "gzip, deflate",
    "Accept": "*/*",
    "Connection": "keep-alive",
}


SHOP = "Casemod"

IMAGE_SHOP_DIR = f"{IMAGE_BASE_DIR}/{SHOP.lower()}"


async def process_response(session, response, url):
    product = {"url": url}
    product_data = response.xpath("//div[@id='product-details']/@data-product")
    if not product_data:
        product["error_message"] = error.PRODUCT_DATA_NOT_FOUND
        product["error"] = True
        return product
    product_data = ujson.loads(product_data[0])

    code = product_data.get("id_product", None)
    if not code:
        product["error_message"] = error.CODE_NOT_FOUND
        product["error"] = True
        return product
    product["code"] = int(code)

    name = product_data.get("name", None)
    if not name:
        product["error_message"] = error.PRODUCT_NAME_NOT_FOUND
        product["error"] = True
        return product
    product["name"] = name

    part_number = product_data.get("reference", None)
    if not part_number:
        product["error_message"] = error.PARTNUMBER_NOT_FOUND
        product["error"] = True
        return product
    product["part_number"] = part_number
    #

    stock = product_data.get("availability", "unavailable")
    stock = True if stock == "available" else False
    product["stock"] = stock

    price = product_data.get("price_amount", -1)
    product["price"] = parse_number(price)

    category = response.xpath("(//span[@itemprop='name'])[3]/text()")
    category = category[0] if category else None
    product["category"] = category

    images = product_data.get("images", [])
    medium_images = []
    large_images = []
    for image in images:
        medium_img = image.get("medium", {}).get("url", None)
        if medium_img:
            medium_images.append(medium_img)

        large_img = image.get("large", {}).get("url", None)
        if large_img:
            large_images.append(large_img)

    #
    images = {}
    image_size = "medium"
    medium_images = await download_save_images(session, medium_images, part_number, code, image_size, IMAGE_SHOP_DIR)
    if medium_images == "Ya exiten":
        pass
    if medium_images:
        images["medium"] = medium_images

    image_size = "large"
    large_images = await download_save_images(session, large_images, part_number, code, image_size, IMAGE_SHOP_DIR, check=False)
    if large_images == "Ya exiten":
        pass
    if large_images:
        images["large"] = large_images

    category = product_regex.validate_category(category)
    if not category:
        product["error_message"] = error.CATEGORY_NOT_FOUND
        product["error"] = True
        return product
    product["category"] = category

    if category == "CPU Cooler" or category == "Chassis":
        result = product_regex.process_product(product, SHOP, 0, add_product=False)
    else:
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
        logger.error(error.parse_html(url))
        return False, error.HTML_PARSE_ERROR

    return True, response


async def main(logger, shop_data):
    if not shop_data:
        return False

    try:
        conn = aiohttp.TCPConnector(limit=15)
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(connector=conn, timeout=timeout, headers=HEADERS) as session:
            for entry in range(len(shop_data)):
                url = shop_data[entry]["url"]
                result, response = await download_data(logger, session, url, proxy=random.choice(KubernetesProxyList))
                if not result:
                    shop_data[entry]["result"] = {"error": True, "error_message": response}
                    continue

                shop_data[entry]["result"] = await process_response(session, response, url)

    except asyncio.exceptions.TimeoutError:
        logger.error(error.TIMEOUT_ERROR)
        return []

    return shop_data
