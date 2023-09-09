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

SHOP = "Versus Gamers"
IMAGE_SHOP_DIR = f"{IMAGE_BASE_DIR}/vsgamers"


async def process_response(logger, session, product, only_download_images):
    url = product.get("url", None)
    code = product.get("id", None)
    name = product.get("name", None)
    medium_images = product.get("images", None)
    part_number = product.get("sku", None)
    category = product.get("category", None)
    manufacturer = product.get("brand", None)
    price = parse_number(product.get("price", -1))
    stock = True if product.get("stockAvailability", "").find("yes") != -1 else False

    #
    large_images = []
    for image in medium_images:
        large_images.append(image.replace("product_gallery_medium", "product_gallery_large"))

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
        product["error_message"] = error.CATEGORY_NOT_FOUND
        product["error"] = True
        return product
    product["category"] = category

    images = {}
    image_sizes = {"medium": medium_images, "large": large_images}

    for size, image_list in image_sizes.items():
        if not image_list:
            continue
        image = await download_save_images(logger, session, image_list, part_number, code, size, IMAGE_SHOP_DIR, check=False)
        if image:
            images[size] = image

    if not images["medium"] and not images["large"]:
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

    product_data = response.xpath("//div[@class='vs-product']/@data-info")
    images = response.xpath("//div[@class='thumbnails']//div[@class='wrapper']//ul//li//a/@href")
    if not product_data:
        return False, error.ARTICLES_NOT_FOUND

    try:
        product_data = ujson.loads(product_data[0])
    except:
        return False, error.JSON_ERROR

    product_data["url"] = url
    product_data["images"] = images
    return product_data, response


async def main(logger, shop_data, only_download_images = False):
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
