import asyncio

import aiohttp
import ujson
from sqlalchemy import and_

import app.common.shops.urls.casemod as casemod_data
import app.database_functions as database_functions
import app.scripts.stock.database_handler as database_handler
import app.shared.auxiliary.inputs as auxiliary_inputs
import app.shared.auxiliary.requests_handler as requests_handler
import app.shared.error_messages as error
import app.shared.valid_messages as valid
from app.shared.auxiliary.functions import parse_number
from app.stockfinder_models.Availability import Availability
from app.stockfinder_models.base import Session

SHOP = "Casemod"
HEADERS = {
    "Host": "casemod.es",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "es-ES,es;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "X-Requested-With": "XMLHttpRequest",
    "DNT": "1",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Sec-GPC": "1",
}


async def scrape_data(logger, response, category):
    shop_id = 10
    casemod_db_data = database_functions.perform_select_availabilities(
        search_params={"shop_id": shop_id}, select_params={"code"}, distinct=True, as_dict=True, data_askey=True, key="code"
    )

    products = response.get("products", [])
    update_products = []
    first_check = True
    add_vat = False
    for product in products:
        code = product.get("id_product", None)
        if not code:
            logger.warning(error.CODE_NOT_FOUND)
            continue
        code = int(parse_number(code))

        price = product.get("price_amount", None)
        if not price:
            logger.warning(error.PRODUCT_PRICE_NOT_FOUND)
            continue
        price = parse_number(price)

        stock = product.get("add_to_cart_url", None)
        stock = True if stock else False

        # We can receive products without TAX
        if first_check:
            session = Session()
            result = session.query(Availability).filter(and_(Availability.shop_id == shop_id, Availability.code == code)).first()

            db_price = 0
            if result:
                result = result.__dict__
                first_check = False
                db_price = result.get("price", 0)
                add_vat = True if round(float(price * 1.21), 2) == round(float(db_price), 2) else False

            session.close()
            logger.info(f"add_vat: {add_vat} - price: {price} - db_price: {db_price} - availability: {result}")

        price = parse_number(price * 1.21) if add_vat else price

        name = product.get("name", None)
        if not name:
            logger.warning(error.PRODUCT_NAME_NOT_FOUND)
            continue
        name = auxiliary_inputs.fix_name(name)

        url = product.get("url", None)
        if not url:
            logger.warning(error.URL_NOT_FOUND)
            continue

        json_product = {"url": url, "name": name, "code": code, "price": price, "stock": stock, "category": category}
        shop_data = {"shop_name": SHOP, "shop_db_data": casemod_db_data, "shop_id": shop_id}
        result, product_tuple = database_handler.add_product(logger, shop_data, json_product)
        if result == False:
            continue
        update_products.append(product_tuple)
        continue

    return update_products


async def download_data(logger, session, url, category):
    currrent_page = True
    update_products = []
    while currrent_page:
        response = await requests_handler.get(logger, session, url, max_redirects=30)
        if not response:
            break

        try:
            response = ujson.loads(response)
        except:
            logger.error(error.parse_json(url))
            break

        result = await scrape_data(logger, response, category)
        if result:
            update_products.extend(result)

        currrent_page = response.get("pagination", {}).get("current_page", False)
        total_page = response.get("pagination", {}).get("pages_count", False)
        logger.info(f"current_page: {currrent_page} - total_page: {total_page}")
        if not currrent_page or not total_page or currrent_page == total_page:
            break

        url = url.replace(f"page={currrent_page}", f"page={currrent_page+1}")

    return update_products


async def main(logger, category_selected=[]):
    try:
        conn = aiohttp.TCPConnector(limit=60)
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(connector=conn, timeout=timeout, headers=HEADERS) as session:
            for category in casemod_data.urls:
                if len(category_selected) > 0 and category not in category_selected:
                    continue
                elif (category == "GPU" or category == "CPU") and len(category_selected) == 0:
                    continue

                url = casemod_data.urls[category]
                update_products = await download_data(logger, session, url, category)
                database_handler.process_data(logger, update_products)

    except asyncio.exceptions.TimeoutError:
        logger.error(error.TIMEOUT_ERROR)
