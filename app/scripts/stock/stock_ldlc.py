import asyncio
import random
import re
import time

import aiohttp
import lxml.html
import ujson
import unidecode

import app.common.shops.urls.ldlc as ldlc_data
import app.database_functions as database_functions
import app.scripts.stock.database_handler as database_handler
import app.shared.auxiliary.inputs as auxiliary_inputs
import app.shared.auxiliary.requests_handler as requests_handler
import app.shared.error_messages as error
import app.shared.valid_messages as valid
from app.shared.auxiliary.functions import parse_number

SHOP = "LDLC"
WEB = "https://www.ldlc.com"
HEADERS = {
    "Host": "www.ldlc.com",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:103.0) Gecko/20100101 Firefox/103.0",
    "Accept": "*/*",
    "Accept-Language": "es-ES,es;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Length": "41",
    "Origin": "https://www.ldlc.com",
    "DNT": "1",
    "Connection": "keep-alive",
    "Cookie": "Session=ID%3D2746164615082022611919168134169139; Geolocation=270004; consent_country=es-es",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Sec-GPC": "1",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
}
DATA = "filter%5BsearchText%5D=&sorting=Ventas&filter%5Bsort%5D="


async def scrape_data(logger, response, url, category):
    listing = response.get("listing", None)

    try:
        listing = lxml.html.fragment_fromstring(listing)
    except:
        logger.error(error.parse_html(url))
        return None

    shop_id = 5
    ldlc_db_data = database_functions.perform_select_availabilities(
        search_params={"shop_id": shop_id}, select_params={"code"}, distinct=True, as_dict=True, data_askey=True, key="code"
    )

    products = listing.xpath("(.//div[@class='listing-product'])//li[@class='pdt-item']")
    update_products = []

    for product in products:
        url = product.xpath("(.//h3[@class='title-3']//a/@href)")
        if not url:
            continue
        url = url[0]

        code_string = re.findall("PB\d+", url)
        if not code_string:
            continue
        code_string = re.findall("\d+", code_string[0])
        if not code_string:
            continue
        code = int(code_string[0])

        try:
            price_int = product.xpath("(.//div[@class='basket'])//div//div/text()")[0].replace("€", "")
            price_int = parse_number(unidecode.unidecode(price_int).replace(" ", ""))
            price_dec = product.xpath("(.//div[@class='basket'])//div//div//sup/text()")[0]
            price = parse_number(str(price_int) + "." + str(price_dec))
        except:
            price = -1

        stock1 = product.xpath("(.//div[@data-stock-web='9'])")
        stock2 = product.xpath("(.//div[@data-stock-web='10'])")
        stock = True if (not stock1 and not stock2) else False

        url = WEB + url
        name = product.xpath("(.//h3[@class='title-3'])//a/text()")
        if not name:
            logger.warning(error.PRODUCT_NAME_NOT_FOUND)
            continue
        name = auxiliary_inputs.fix_name(name[0])

        description = product.xpath(".//div[@class='pdt-desc']//p/text()")
        description = description[0] if description else None

        json_product = {"url": url, "name": name, "code": code, "price": price, "stock": stock, "category": category, "description": description}
        shop_data = {"shop_name": SHOP, "shop_db_data": ldlc_db_data, "shop_id": shop_id}
        result, product_tuple = database_handler.add_product(logger, shop_data, json_product)
        if result == False:
            continue
        update_products.append(product_tuple)
        continue

    current_page = response.get("page", None)
    try:
        total_page = listing.xpath("(.//li[@class='next'])//a/@data-page")[0]
    except:
        total_page = current_page

    return update_products, current_page, total_page


async def main(logger, category_selected=[]):
    url_dict = ldlc_data.urls
    try:
        conn = aiohttp.TCPConnector(limit=60)
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(connector=conn, timeout=timeout, headers=HEADERS) as session:
            for category in url_dict:
                if len(category_selected) > 0 and category not in category_selected:
                    continue
                elif (category == "GPU" or category == "CPU") and len(category_selected) == 0:
                    continue

                url_list = url_dict[category]

                for url in url_list:
                    update_products = []
                    current_page = 1

                    while current_page:
                        HEADERS["Refer"] = f"{url}"

                        response = await requests_handler.post(logger, session, url, data=DATA, headers=HEADERS)
                        if not response:
                            continue

                        try:
                            response = ujson.loads(response)
                        except:
                            logger.error(error.parse_json(url))
                            continue

                        products_list, current_page, next_page = await scrape_data(logger, response, url, category)
                        logger.info(valid.actual_next_page(current_page, next_page, url))

                        wait_time = random.randint(3000, 5000) / 1000
                        time.sleep(wait_time)

                        if products_list:
                            update_products += products_list
                        if not current_page or not next_page or current_page == next_page:
                            break
                        if current_page == 1:
                            url = url.replace(f"page", f"page{next_page}")
                        else:
                            url = url.replace(f"page{current_page}", f"page{next_page}")

                    database_handler.process_data(logger, update_products)

    except asyncio.exceptions.TimeoutError:
        logger.error(error.TIMEOUT_ERROR)
        return False

    return True
