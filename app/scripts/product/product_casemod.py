import asyncio
import logging
import random
import re

import aiohttp
import app.shared.auxiliary.requests_handler as requests_handler
import app.shared.error_messages as error
import app.shared.regex.product as regex_product
import app.shared.valid_messages as valid
import lxml.html
import ujson
from app.shared.auxiliary.functions import download_save_images, parse_number
from app.shared.environment_variables import IMAGE_BASE_DIR

HEADERS = {
    "Accept-Encoding": "gzip, deflate",
    "Accept": "*/*",
    "Connection": "keep-alive",
}


SHOP = "Casemod"

IMAGE_SHOP_DIR = f"{IMAGE_BASE_DIR}/{SHOP.lower()}"


async def process_response(logger, session, response, url, only_download_images):
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
    image_sizes = {"medium": [], "large": []}

    for image in images:
        for size in image_sizes.keys():
            img_url = image.get(size, {}).get("url", None)
            if img_url:
                image_sizes[size].append(img_url)

    images = {}

    for size, img_list in image_sizes.items():
        img_list = await download_save_images(logger, session, img_list, part_number, code, size, IMAGE_SHOP_DIR)
        if img_list:
            images[size] = img_list

    if only_download_images:
        return product
    
    category = regex_product.validate_category(category)
    if not category:
        product["error_message"] = error.CATEGORY_NOT_FOUND
        product["error"] = True
        return product
    product["category"] = category

    if category == "CPU Cooler" or category == "Chassis":
        result = regex_product.process_product(product, SHOP, 0, add_product=False)
    else:
        result = regex_product.process_product(product, SHOP, 0)

    if not result:
        product["error_message"] = error.PRODUCT_NOT_ADDED
        product["error"] = True

    return product


async def download_data(logger, session, url, proxy=None):
    logger.info(f"Consultando url: {url}")

    response = await requests_handler.get(logger, session, url)
    if not response:
        return False, error.GET_NOT_COMPLETED

    try:
        response = lxml.html.fromstring(response)
    except:
        logger.error(error.parse_html(url))
        return False, error.HTML_PARSE_ERROR

    return True, response


async def main(logger, shop_data, only_download_images=False):
    if not shop_data:
        return False

    try:
        conn = aiohttp.TCPConnector(limit=15)
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(connector=conn, timeout=timeout, headers=HEADERS) as session:
            for entry in range(len(shop_data)):
                url = shop_data[entry]["url"]
                result, response = await download_data(logger, session, url)
                if not result:
                    shop_data[entry]["result"] = {"error": True, "error_message": response}
                    continue

                shop_data[entry]["result"] = await process_response(logger, session, response, url, only_download_images)

    except asyncio.exceptions.TimeoutError:
        logger.error(error.TIMEOUT_ERROR)
        return []

    return shop_data
