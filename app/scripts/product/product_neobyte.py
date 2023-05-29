import re

import aiohttp
import lxml.html
import ujson

import app.shared.auxiliary.requests_handler as requests_handler
import app.shared.error_messages as error
import app.shared.regex.product as regex_product
import app.shared.valid_messages as valid
from app.shared.auxiliary.functions import download_save_images, parse_number
from app.shared.environment_variables import IMAGE_BASE_DIR, PersonalProxy

HEADERS = {
    "Accept-Encoding": "gzip, deflate",
    "Accept": "*/*",
    "Connection": "keep-alive",
}

SHOP = "Neobyte"
IMAGE_SHOP_DIR = f"{IMAGE_BASE_DIR}/{SHOP.lower()}"


async def process_product(logger, session, product):
    url = product.get("url", None)
    code_str = re.findall("\d+.html", url, re.IGNORECASE)
    if code_str:
        code = int(re.findall("\d+", code_str[0], re.IGNORECASE)[0])
    else:
        code = None

    name = product.get("name", None)
    images = product.get("images", None)
    part_number = product.get("mpn", None)
    try:
        category = name.split(" - ")[1]
    except:
        category = None

    manufacturer = product.get("brand", {}).get("name", None)
    price = parse_number(product.get("offers", {}).get("price", -1))
    stock = True if product.get("offers", {}).get("availability", "").find("InStock") != -1 else False

    #
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

    category = regex_product.validate_category(category)
    if not category:
        category = regex_product.validate_category(name, short=False)
    if not category:
        category = regex_product.validate_category(url, short=False)
        product["error_message"] = error.CATEGORY_NOT_FOUND
        product["error"] = True
        return product
    product["category"] = category

    image_size = "large"
    images = await download_save_images(session, images, part_number, code, image_size, IMAGE_SHOP_DIR, proxy=True)
    if not images:
        product["error_message"] = error.PRODUCT_IMG_NOT_FOUND
        product["error"] = True
        return product

    if category == "CPU Cooler" or category == "Chassis":
        result = regex_product.process_product(product, SHOP, 0, add_product=False)
    else:
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

    product_data = response.xpath("//script[@id='microdata-product-script']/text()")
    images = response.xpath("//div[contains(@class,'product-lmage-large swiper-slide')]//img/@data-image-large-src")
    if not product_data:
        return False, error.ARTICLES_NOT_FOUND

    try:
        product_data = ujson.loads(product_data[0])
    except:
        return False, error.JSON_ERROR

    product_data["url"] = url
    product_data["images"] = images
    return product_data, response


async def main(logger, shop_data):
    if not shop_data:
        return False

    conn = aiohttp.TCPConnector(limit=15)
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(connector=conn, timeout=timeout, headers=HEADERS) as session:
        for entry in range(len(shop_data)):
            url = shop_data[entry]["url"]
            product_data, response = await download_data(logger, session, url, proxy=PersonalProxy)
            if product_data == False:
                shop_data[entry]["result"] = {"error": True, "error_message": response}
                continue

            shop_data[entry]["result"] = await process_product(logger, session, product_data)

    return shop_data
