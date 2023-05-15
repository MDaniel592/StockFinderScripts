import asyncio
import datetime
import random

import aiohttp
import ujson
from sqlalchemy import and_

import app.scripts.stock.database_handler as database_handler
import app.utils.error_messages as error
import app.utils.requests_handler as requests_handler
import app.utils.shops.urls.nvidia as nvidia_data
import app.utils.valid_messages as valid
from app.stockfinder_models.Alert import Alert
from app.stockfinder_models.Availability import Availability
from app.stockfinder_models.base import Base, Session, engine
from app.stockfinder_models.Category import Category
from app.stockfinder_models.Manufacturer import Manufacturer
from app.stockfinder_models.Message import Message
from app.stockfinder_models.Product import Product
from app.stockfinder_models.ProductSpec import ProductSpec
from app.stockfinder_models.Role import Role
from app.stockfinder_models.Shop import Shop
from app.stockfinder_models.Spec import Spec
from app.stockfinder_models.TelegramChannel import TelegramChannel
from app.stockfinder_models.User import User
from app.utils.aux_functions import parse_number
from app.utils.shared_variables import KubernetesProxyList

######################
######################
######################
#
# Script deployed on Kubernetes. There is a repo with the docker image
#
######################
######################
######################
HEADERS = {
    "Host": "api.store.nvidia.com",
    "Origin": "https://store.nvidia.com",
    "Refer": "https://store.nvidia.com",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:101.0) Gecko/20100101 Firefox/101.0",
    "Accept": "*/*",
    "Accept-Language": "es-ES,es;q=0.8,en-US;q=0.5,en;q=0.3",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "close",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
    "Sec-GPC": "1",
    "Cache-Control": "max-age=0",
    "TE": "trailers",
}

GPU_MODEL = {
    "NVGFT060T_ES": {"code": 1, "url": "https://store.nvidia.com/es-es/geforce/store/?page=1&limit=9&locale=es-es&gpu=RTX+3060+Ti&manufacturer=NVIDIA"},
    "NVGFT060T_FR": {"code": 1, "url": "https://store.nvidia.com/es-es/geforce/store/?page=1&limit=9&locale=es-es&gpu=RTX+3060+Ti&manufacturer=NVIDIA"},
    "NVGFT060T_IT": {"code": 1, "url": "https://store.nvidia.com/es-es/geforce/store/?page=1&limit=9&locale=es-es&gpu=RTX+3060+Ti&manufacturer=NVIDIA"},
    #
    "NVGFT070_ES": {"code": 2, "url": "https://store.nvidia.com/es-es/geforce/store/?page=1&limit=9&locale=es-es&gpu=RTX+3070&manufacturer=NVIDIA"},
    "NVGFT070_FR": {"code": 2, "url": "https://store.nvidia.com/es-es/geforce/store/?page=1&limit=9&locale=es-es&gpu=RTX+3070&manufacturer=NVIDIA"},
    "NVGFT070_IT": {"code": 2, "url": "https://store.nvidia.com/es-es/geforce/store/?page=1&limit=9&locale=es-es&gpu=RTX+3070&manufacturer=NVIDIA"},
    #
    "NVGFT080_ES": {"code": 3, "url": "https://store.nvidia.com/es-es/geforce/store/?page=1&limit=9&locale=es-es&gpu=RTX+3080&manufacturer=NVIDIA"},
    "NVGFT080_FR": {"code": 3, "url": "https://store.nvidia.com/es-es/geforce/store/?page=1&limit=9&locale=es-es&gpu=RTX+3080&manufacturer=NVIDIA"},
    "NVGFT080_IT": {"code": 3, "url": "https://store.nvidia.com/es-es/geforce/store/?page=1&limit=9&locale=es-es&gpu=RTX+3080&manufacturer=NVIDIA"},
    #
    "NVGFT480_ES": {"code": 5, "url": "https://store.nvidia.com/es-es/geforce/store/?page=1&limit=9&locale=es-es&gpu=RTX+4080&manufacturer=NVIDIA"},
    "NVGFT480_FR": {"code": 5, "url": "https://store.nvidia.com/es-es/geforce/store/?page=1&limit=9&locale=es-es&gpu=RTX+4080&manufacturer=NVIDIA"},
    "NVGFT480_IT": {"code": 5, "url": "https://store.nvidia.com/es-es/geforce/store/?page=1&limit=9&locale=es-es&gpu=RTX+4080&manufacturer=NVIDIA"},
    #
    "NVGFT490_ES": {"code": 4, "url": "https://store.nvidia.com/es-es/geforce/store/?page=1&limit=9&locale=es-es&gpu=RTX+4090&manufacturer=NVIDIA"},
    "NVGFT490_FR": {"code": 4, "url": "https://store.nvidia.com/es-es/geforce/store/?page=1&limit=9&locale=es-es&gpu=RTX+4090&manufacturer=NVIDIA"},
    "NVGFT490_IT": {"code": 4, "url": "https://store.nvidia.com/es-es/geforce/store/?page=1&limit=9&locale=es-es&gpu=RTX+4090&manufacturer=NVIDIA"},
}
NVIDIA_SHOP_ID = 9


async def process_data(logger, product_data, proxy_chosen=None):

    name = product_data["fe_sku"]
    region = product_data["locale"]
    url = product_data["product_url"]
    active = product_data["is_active"]
    price = parse_number(product_data["price"])

    new_product_data = {"url": url, "name": name, "price": price, "region": region, "active": active}
    if not GPU_MODEL.get(name, False):
        return None

    logger.info(valid.nvidia_custom_msg(new_product_data, f"Se han recogido los datos - Proxy {proxy_chosen}"))
    try:
        code = int(GPU_MODEL[name]["code"])
        db_url = str(GPU_MODEL[name]["url"])
    except:
        return logger.warning(valid.nvidia_custom_msg(new_product_data, "Producto no identificado - código o url erróneo"))

    session = Session()
    availability_db = session.query(Availability).filter(and_(Availability.code == code, Availability.shop_id == NVIDIA_SHOP_ID)).first()
    if not availability_db:
        logger.warning(error.product_not_in_DB(new_product_data))
        session.close()
        return None

    current_time = datetime.datetime.now().replace(microsecond=0)

    if availability_db.stock == False and active == "true" and db_url:
        logger.info(valid.nvidia_custom_msg(new_product_data, "Tiene stock"))
        availability_db.stock = True
        availability_db.price = price
        session.commit()

    elif availability_db.stock == True and active == "false" and current_time > availability_db.updated_at + datetime.timedelta(minutes=180):
        logger.info(valid.nvidia_custom_msg(new_product_data, "Sin stock"))
        availability_db.stock = False
        session.commit()

    else:
        logger.info(valid.nvidia_custom_msg(new_product_data, "No se actualiza la DB"))

    session.close()


async def scrape_api(logger, url):
    try:
        timeout = aiohttp.ClientTimeout(total=4)
        async with aiohttp.ClientSession(timeout=timeout, headers=HEADERS) as session:
            response = await requests_handler.get(logger, session, url)
            if not response:
                return

        try:
            json_response = ujson.loads(response)
        except:
            logger.error(error.JSON_ERROR)
            return

        products_data = json_response["listMap"]
        await asyncio.gather(*[process_data(logger, product_data) for product_data in products_data])

    except asyncio.exceptions.TimeoutError:
        logger.error(error.TIMEOUT_ERROR)


async def main(logger, category_selected=[]):
    await asyncio.gather(*[scrape_api(logger, url) for url in nvidia_data.API_URLS])
