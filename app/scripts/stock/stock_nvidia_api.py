import asyncio
import datetime
import json
import logging
import math
import re
import time
import typing

import aiohttp
from influxdb_client import InfluxDBClient
from influxdb_client.client.exceptions import InfluxDBError
from influxdb_client.client.write_api import SYNCHRONOUS
from sqlalchemy import and_, func
from urllib3.exceptions import ReadTimeoutError

import app.shared.environment_variables as ev
import app.shared.error_messages as error
import app.shared.regex.product as regex_product
import app.shared.valid_messages as valid
from app.shared.auxiliary.functions import parse_number
from app.stockfinder_models.Alert import Alert
from app.stockfinder_models.Availability import Availability
from app.stockfinder_models.base import Base, Session, engine
from app.stockfinder_models.Category import Category
from app.stockfinder_models.Manufacturer import Manufacturer
from app.stockfinder_models.Message import Message
from app.stockfinder_models.Product import Product
from app.stockfinder_models.ProductPartNumber import ProductPartNumber
from app.stockfinder_models.ProductSpec import ProductSpec
from app.stockfinder_models.Role import Role
from app.stockfinder_models.Shop import Shop
from app.stockfinder_models.Spec import Spec
from app.stockfinder_models.TelegramChannel import TelegramChannel
from app.stockfinder_models.User import User

SERVICE_NAME = "Nvidia"

API_URLS = [
    # RTX 4000
    "https://api.store.nvidia.com/partner/v1/feinventory?skus=NVGFT460T&locale=es-es",
    "https://api.store.nvidia.com/partner/v1/feinventory?skus=NVGFT470&locale=es-es",
    "https://api.store.nvidia.com/partner/v1/feinventory?skus=NVGFT480&locale=es-es",
    "https://api.store.nvidia.com/partner/v1/feinventory?skus=NVGFT490&locale=es-es",
]


HEADERS = {
    "authority": "api.store.nvidia.com",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Encoding": "gzip,deflate,br",
    "accept-language": "en-US,en;q=0.8",
    "cache-control": "max-age=0",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "sec-gpc": "1",
    "upgrade-insecure-requests": "1",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
}


NVIDIA_SHOP_ID = 9


logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


class BatchingCallback(object):
    def success(self, conf: typing.Tuple[str, str, str], data: str):
        logger.info(f"Written batch: {conf}, data: {data}")

    def error(self, conf: typing.Tuple[str, str, str], data: str, exception: InfluxDBError):
        logger.error(f"Cannot write batch: {conf}, data: {data} due: {exception}")

    def retry(self, conf: typing.Tuple[str, str, str], data: str, exception: InfluxDBError):
        logger.warning(f"Retryable error occurs for batch: {conf}, data: {data} retry: {exception}")


async def process_data(product, proxy_chosen):
    price = product.get("price", None)
    active = product.get("is_active", None)
    part_number = product.get("fe_sku", None)

    if not active or not part_number or not price:
        logger.warning(f"Faltan datos {product}")
        return

    price = parse_number(price)
    part_number = part_number.split("_")[0]
    active = True if active == "true" else False
    try:
        gpu_model = re.findall("\d+T", part_number)[0].replace("4", "40").replace("T", " Ti")
    except:
        gpu_model = re.findall("\d+", part_number)[0].replace("4", "40")

    name = "NVIDIA GeForce RTX " + gpu_model
    gpu_model = gpu_model.replace(" ", "%20")
    url = f"https://store.nvidia.com/es-es/geforce/store/?page=1&limit=9&locale=es-es&gpu=RTX%20{gpu_model}&category=GPU,DESKTOP"

    new_product = {"url": url, "name": name, "part_number": part_number, "price": price, "stock": active}

    session = Session()
    ProductPartNumber_db = session.query(ProductPartNumber).filter(ProductPartNumber.part_number == part_number).first()
    if not ProductPartNumber_db:
        highest_code = session.query(func.max(Availability.code)).filter(Availability.shop_id == NVIDIA_SHOP_ID).first()

        new_product["category"] = "GPU"
        new_product["manufacturer"] = "NVIDIA"
        new_product["code"] = int(highest_code[0]) + 1
        logger.warning(f"Producto no registrado: {product} \n {new_product}")

        # Registrar nuevo producto
        result = regex_product.process_product(new_product, "NVIDIA", 0)
        if result == 0:
            logger.warning(f"No se ha registrado el producto")
            session.close()
            return

        # ASOCIAR LA ALERTA AL USUARIO
        ProductPartNumber_db = session.query(ProductPartNumber).filter(ProductPartNumber.part_number == part_number).first()
        if not ProductPartNumber_db:
            logger.error(f"No se ha obtenido el ProductPartNumber")
            session.close()
            return

        new_alert = Alert(
            user_id=1390,
            product_id=ProductPartNumber_db.product_id,
            max_price=math.ceil(price / 100) * 100,
            alert_by_telegram=True,
            alert_by_email=False,
        )
        session.add(new_alert)
        session.close()
        logger.error(f"Se ha creado la alerta {new_alert}")
        return

    logger.info(valid.nvidia_custom_msg(new_product, f"Se han recogido los datos - Proxy {proxy_chosen}"))
    availability_db = session.query(Availability).filter(and_(Availability.product_id == ProductPartNumber_db.product_id)).first()
    if not availability_db:
        logger.warning(error.product_not_in_DB(new_product))
        session.close()
        return

    logger.info(valid.nvidia_custom_msg(new_product, "Se actualiza la DB"))
    data = {"url": url, "stock": active, "price": price}
    availability_db = (
        session.query(Availability).filter(and_(Availability.product_id == ProductPartNumber_db.product_id)).update(data, synchronize_session=False)
    )
    session.commit()
    session.close()


async def scrape_api(url):
    try:
        timeout = aiohttp.ClientTimeout(total=7)
        async with aiohttp.ClientSession(timeout=timeout, headers=HEADERS) as session:
            proxy_chosen = None
            async with session.get(url, proxy=proxy_chosen) as response:
                if response.status != 200:
                    return logger.error(error.code_not_200(url, response.status))

                response = await response.text()

        try:
            json_response = json.loads(response)
        except:
            logger.error(error.JSON_ERROR)
            return logger.error(response)

        logger.info(valid.url_successful(url))
        await asyncio.gather(*[process_data(product, proxy_chosen=proxy_chosen) for product in json_response["listMap"]])

    except asyncio.exceptions.TimeoutError:
        logger.error(error.TIMEOUT_ERROR)

    except aiohttp.client.ClientConnectorError:
        logger.error(error.HTTP_PROXY_ERROR)

    except:
        logger.error("Error desconocido")


async def main():
    sleep()
    t0 = datetime.datetime.now()
    logger.info(f"The Scrape of {SERVICE_NAME} for checking the stock will start")

    for url in API_URLS:
        await scrape_api(url)

    t1 = datetime.datetime.now()
    elapsed_time = float(round((t1 - t0).total_seconds() * 1000))
    logger.info(f"The Scrape of {SERVICE_NAME} has finished - elapsed_time: {elapsed_time} ms")

    actual_time = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    client = InfluxDBClient(url=ev.INFLUXDB_URL, token=ev.INFLUXDB_TOKEN, org=ev.INFLUXDB_ORG)
    callback = BatchingCallback()
    write_api = client.write_api(write_options=SYNCHRONOUS, success_callback=callback.success, error_callback=callback.error, retry_callback=callback.retry)

    try:
        write_api.write(
            bucket=ev.INFLUXDB_BUCKET,
            record=[
                {
                    "measurement": "Stock",
                    "tags": {"service": f"Check Stock {SERVICE_NAME}"},
                    "fields": {"Elapsed time": elapsed_time},
                    "time": actual_time,
                }
            ],
        )
    except ReadTimeoutError:
        pass

    await asyncio.sleep(90)


def sleep():
    current_hour = int(datetime.datetime.utcnow().strftime("%H"))
    if current_hour == 22:
        sleep_time = 9 * 60
        time.sleep(sleep_time)
