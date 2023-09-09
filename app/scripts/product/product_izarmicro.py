import asyncio
import random
import re

import aiohttp
import app.shared.auxiliary.requests_handler as requests_handler
import app.shared.error_messages as error
import app.shared.regex.product as regex_product
import app.shared.valid_messages as valid
import lxml.html
from app.shared.auxiliary.functions import download_save_images
from app.shared.environment_variables import IMAGE_BASE_DIR

HEADERS = {
    "Accept-Encoding": "gzip, deflate",
    "Accept": "*/*",
    "Connection": "keep-alive",
}


SHOP = "IzarMicro"

IMAGE_SHOP_DIR = f"{IMAGE_BASE_DIR}/{SHOP.lower()}"


async def process_response(logger, session, response, url, only_download_images):
    product = {"url": url}
    product_data = response.xpath("//div[@class='datos_art_responsive']")
    if not product_data:
        product["error_message"] = error.PRODUCT_DATA_NOT_FOUND
        product["error"] = True
        return product
    product_data = product_data[0]

    code = re.findall("art-\d+", url)
    if not code:
        product["error_message"] = error.CODE_NOT_FOUND
        product["error"] = True
        return product
    code = re.findall("\d+", code[0])
    if not code:
        product["error_message"] = error.CODE_NOT_FOUND
        product["error"] = True
        return product
    code = code[0]
    product["code"] = code

    name = product_data.xpath("h1/text()")
    if not name:
        product["error_message"] = error.PRODUCT_NAME_NOT_FOUND
        product["error"] = True
        return product
    product["name"] = name[0]

    part_number = product_data.xpath("//span[@itemprop='sku']/text()")
    if not part_number:
        product["error_message"] = error.PARTNUMBER_NOT_FOUND
        product["error"] = True
        return product
    part_number = part_number[0]
    product["part_number"] = part_number
    #
    second_name = product_data.xpath("//p[@itemprop='description']/text()")
    second_name = second_name[0] if second_name else None
    product["second_name"] = second_name

    stock = product_data.xpath("(//span[@class='txikicolorart']//span)[2]")
    if stock:
        stock = True if stock[0].find("InStock") != -1 else False
    else:
        stock = False
    product["stock"] = stock

    price = product_data.xpath("//span[@itemprop='price']/text()")
    price = price[0] if price else -1
    product["price"] = price

    manufacturer = product_data.xpath("//span[@class='marca']//a[1]/text()")
    manufacturer = manufacturer[0] if manufacturer else None
    product["manufacturer"] = manufacturer

    category = product_data.xpath("(//span[@itemprop='name'])[3]/text()")
    category = category[0] if category else None
    product["category"] = category

    first_image = response.xpath("//a[@itemprop='image']/@href")
    image_size = "medium"
    images = response.xpath("//div[@class='thum_art2']//ul//li//a/@href")
    if first_image:
        images.insert(0, first_image[0])

    category = regex_product.validate_category(category)
    if not category:
        product["error_message"] = error.CATEGORY_NOT_FOUND
        product["error"] = True
        return product
    product["category"] = category

    images = await download_save_images(logger, session, images, part_number, code, image_size, IMAGE_SHOP_DIR)
    if not images:
        product["error_message"] = error.PRODUCT_IMG_NOT_FOUND
        product["error"] = True
        return product

    if only_download_images:
        return product
    
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
