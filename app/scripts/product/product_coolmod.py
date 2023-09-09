import asyncio
import re

import aiohttp
import app.common.shops.regex.coolmod as coolmod_aux_functions
import app.shared.auxiliary.requests_handler as requests_handler
import app.shared.error_messages as error
import app.shared.regex.product as regex_product
import app.shared.valid_messages as valid
import lxml.html
import ujson
from app.shared.auxiliary.functions import download_save_images, parse_number
from app.shared.environment_variables import IMAGE_BASE_DIR

HEADERS = {
    "Host": "www.coolmod.com",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:103.0) Gecko/20100101 Firefox/103.0",
    "Accept": "*/*",
    "Accept-Language": "es-ES,es;q=0.8,en-US;q=0.5,en;q=0.3",
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

SHOP = "Coolmod"
IMAGE_SHOP_DIR = f"{IMAGE_BASE_DIR}/{SHOP.lower()}"


async def process_response(logger, session, product, response, only_download_images):
    code = product.get("sku", "0")
    url = product.get("url", None)
    name = product.get("name", None)
    images = product.get("images", None)
    category = product.get("category", None)
    part_number = product.get("productID", None)
    manufacturer = product.get("brand", {}).get("name", None)  #
    price = parse_number(product.get("offers", {}).get("price", -1))
    stock = False

    product["part_number"] = part_number
    product["manufacturer"] = manufacturer

    code = re.findall("\d+", code)
    if not code:
        logger.warning("No code")
        product["error_message"] = error.CODE_NOT_FOUND
        product["error"] = True
        return product

    code = int(code[0])
    product["code"] = code

    if not category or category == "Reacondicionado":
        category = name.split("-")
        category = category[len(category) - 1]

    product["category"] = category
    category = regex_product.validate_category(category)
    if not category:
        product["error_message"] = error.CATEGORY_NOT_FOUND
        product["error"] = True
        return product

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

    new_product = coolmod_aux_functions.scrape_category(response, product, category)
    error_message = None
    if not new_product:
        error_message = error.SPECS_NOT_FOUND
    else:
        product = new_product

    image_size = "large"
    images = await download_save_images(logger, session, images, part_number, code, image_size, IMAGE_SHOP_DIR)
    if not images:
        logger.warning(error.PRODUCT_IMG_NOT_FOUND)
        product["error_message"] = error.PRODUCT_IMG_NOT_FOUND
        product["error"] = True
        return product

    if only_download_images:
        return product

    if error_message:
        logger.warning(f"Error: {error_message} - Adding availability")
        result = regex_product.process_product(product, SHOP, 0, add_product=False)
    elif category == "CPU Cooler" or category == "Chassis":
        logger.warning(f"{category} is not allowed at this time - Adding availability")
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
        return False, error.HTML_PARSE_ERROR

    product_data = response.xpath("(//script[@type='application/ld+json'])[3]/text()")
    if not product_data:
        return False, error.PRODUCT_DATA_NOT_FOUND

    images = response.xpath("//div[contains(@class,'w-100 productgallery')]//a/@href")
    try:
        product_data = ujson.loads(product_data[0])
    except:
        return False, error.JSON_ERROR

    product_data["images"] = images
    return product_data, response


async def main(logger, shop_data, only_download_images=False):
    if not shop_data:
        return []

    try:
        conn = aiohttp.TCPConnector(limit=15, verify_ssl=False)
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(connector=conn, timeout=timeout, headers=HEADERS, trust_env=True) as session:
            for entry in range(len(shop_data)):
                url = shop_data[entry]["url"]
                product_data, response = await download_data(logger, session, url)
                if not product_data:
                    shop_data[entry]["result"] = {"error": True, "error_message": response}
                    continue

                shop_data[entry]["result"] = await process_response(logger, session, product_data, response, only_download_images)

            return shop_data

    except asyncio.exceptions.TimeoutError:
        logger.error(error.TIMEOUT_ERROR)
        return []
