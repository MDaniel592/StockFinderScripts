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

SHOP = "Speedler"
IMAGE_SHOP_DIR = f"{IMAGE_BASE_DIR}/{SHOP.lower()}"


async def process_response(logger, session, product, only_download_images):
    url = product.get("url", None)
    code = int(product.get("sku", None))
    name = product.get("name", None)
    images = product.get("images", None)
    part_number = product.get("mpn", None)
    category = product.get("category", None)
    manufacturer = product.get("brand", {}).get("name", None)

    offers = product.get("offers", {}).get("offers", {})
    price = parse_number(offers.get("price", -1))
    stock = True if offers.get("availability", "").find("InStock") != -1 else False

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

    image_size = "medium"
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
        return False, error.HTML_PARSE_ERROR

    product_data = response.cssselect("html>body>script:nth-of-type(3)")
    images = response.xpath("//div[contains(@id,'owl-galleryProduct')]//div//img/@src")
    if not product_data:
        return False, error.ARTICLES_NOT_FOUND

    try:
        product_data = ujson.loads(product_data[0].text_content())
    except:
        return False, error.JSON_ERROR

    product_data["url"] = url
    product_data["images"] = images
    return product_data, response


async def main(logger, shop_data, only_download_images=False):
    if not shop_data:
        return False

    conn = aiohttp.TCPConnector(limit=15)
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(connector=conn, timeout=timeout, headers=HEADERS) as session:
        for entry in range(len(shop_data)):
            url = shop_data[entry]["url"]
            product_data, response = await download_data(logger, session, url)
            if product_data == False:
                shop_data[entry]["result"] = {"error": True, "error_message": response}
                continue

            shop_data[entry]["result"] = await process_response(logger, session, product_data, only_download_images)

    return shop_data
