import asyncio

import aiohttp
import ujson

import app.common.shops.urls.aussar as aussar_data
import app.database_functions as database_functions
import app.scripts.stock.database_handler as database_handler
import app.shared.auxiliary.requests_handler as requests_handler
import app.shared.error_messages as error
import app.shared.valid_messages as valid
from app.shared.auxiliary.functions import parse_number
from app.shared.environment_variables import IMAGE_BASE_DIR
                                              

SHOP = "Aussar"
HEADERS = {
    "Host": "www.aussar.es",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/112.0",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "es-ES,es;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-GPC": "1",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "TE": "trailers",
}


IMAGE_SHOP_DIR = f"{IMAGE_BASE_DIR}/{SHOP.lower()}"


async def scrape_data(logger, response, category, http_session):
    shop_id = 2
    aussar_db_data = database_functions.perform_select_availabilities(
        search_params={"shop_id": shop_id}, select_params={"code"}, distinct=True, as_dict=True, data_askey=True, key="code"
    )

    products = response.get("products", None)
    update_products = []

    for product in products:
        product["category"] = category
        product["code"] = int(product.get("id_product", 0))
        product["price"] = parse_number(product.get("price", None))
        product["stock"] = True if product.get("add_to_cart_url", False) else False

        shop_data = {"shop_name": SHOP, "shop_db_data": aussar_db_data, "shop_id": shop_id}
        result, product_tuple = database_handler.add_product(logger, shop_data, product)
        if result == False:
            continue
        update_products.append(product_tuple)
        continue

    current_page = response.get("pagination", None).get("current_page", None)
    total_page = response.get("pagination", None).get("pages_count", None)
    return update_products, current_page, total_page


async def main(logger, category_selected=[]):
    url_dict = aussar_data.urls
    try:
        conn = aiohttp.TCPConnector(limit=60)
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(connector=conn, timeout=timeout, headers=HEADERS) as session:
            for category in url_dict:
                if len(category_selected) > 0 and category not in category_selected:
                    continue
                elif (category == "GPU" or category == "CPU") and len(category_selected) == 0:
                    continue

                url = url_dict[category]
                current_page = 1
                update_products = []
                while current_page:
                    HEADERS["Referer"] = f"https://www.aussar.es/tarjetas-graficas/?page={current_page}"

                    response = await requests_handler.get(logger, session, url)
                    if not response:
                        break

                    try:
                        response = ujson.loads(response)
                    except:
                        logger.error(error.parse_json(url))
                        break

                    products_list, current_page, total_page = await scrape_data(logger, response, category, session)
                    logger.info(valid.actual_total_pages(current_page, total_page, url))

                    if products_list:
                        update_products += products_list

                    if not current_page or not total_page or current_page == total_page:
                        break
                    url = url.replace(f"page={current_page}", f"page={current_page+1}")

                database_handler.process_data(logger, update_products)

    except asyncio.exceptions.TimeoutError:
        logger.error(error.TIMEOUT_ERROR)
        return False

    return True
