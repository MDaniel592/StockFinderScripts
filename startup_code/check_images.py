import logging
import os
import typing
from datetime import datetime

from influxdb_client import InfluxDBClient
from influxdb_client.client.exceptions import InfluxDBError
from influxdb_client.client.write_api import SYNCHRONOUS
from sqlalchemy import and_
from urllib3.exceptions import ReadTimeoutError

import app.scripts.product.product_aussar as aussar
import app.scripts.product.product_casemod as casemod
import app.scripts.product.product_coolmod as coolmod
import app.scripts.product.product_izarmicro as izarmicro
import app.scripts.product.product_ldlc as ldlc
import app.scripts.product.product_neobyte as neobyte
import app.scripts.product.product_speedler as speedler
import app.scripts.product.product_vsgamers as vsgamers
import app.shared.environment_variables as ev
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


class BatchingCallback(object):
    def __init__(self, logger):
        self.logger = logger

    def success(self, conf: typing.Tuple[str, str, str], data: str):
        self.logger.info(f"Written batch: {conf}, data: {data}")

    def error(self, conf: typing.Tuple[str, str, str], data: str, exception: InfluxDBError):
        self.logger.error(f"Cannot write batch: {conf}, data: {data} due: {exception}")

    def retry(self, conf: typing.Tuple[str, str, str], data: str, exception: InfluxDBError):
        self.logger.warning(f"Retryable error occurs for batch: {conf}, data: {data} retry: {exception}")

SHOPS_ID = {
    'ldlc': 5,
    'aussar': 2,
    'coolmod': 3,
    'neobyte': 7,
    'casemod': 10,
    'izarmicro': 4,
    'vsgamers': 12,
    'speedler': 17,
}  
SHOPS_ABSOLUTE_PATH = "/usr/src/StockFinderImages/shops"

def get_availabilities_with_empty_folders(service_name, logger):
    service_name = service_name.replace("versus gamers", "vsgamers")
    service_name = service_name.lower()
    shop_id = SHOPS_ID.get(service_name, False)
    if not shop_id:
        return None
    
    availability_list = []
    session = Session()
    part_numbers_folders = os.listdir(f"{SHOPS_ABSOLUTE_PATH}/{service_name}")
    for folder in part_numbers_folders:
        images = os.listdir(f"{SHOPS_ABSOLUTE_PATH}/{service_name}/{folder}")
        if len(images) > 0:
            continue
        
        product_part_number = folder.upper().replace("_--_", "/")

        result = session.query(ProductPartNumber).filter(ProductPartNumber.part_number == product_part_number).first()
        if not result:
            logger.warning("part_number del producto no encontrado")
            continue
        product_id = result.product._id

        availability_url = session.query(Availability.url).filter(and_(Availability.product_id == product_id, Availability.shop_id == shop_id )).first()
        if not availability_url:
            logger.warning("URL del producto no encontrada")
            continue
        availability_url = availability_url[0]

        availability_list.append({"url": availability_url})

    session.close()
    if len(availability_list) == 0:
        return None

    logger.info(f"The shop {service_name} has a total of {len(availability_list)} empty folders")
    return availability_list

def get_availabilities_without_images(service_name, logger):
    service_name = service_name.lower().replace("versus gamers", "vsgamers")
    shop_id = SHOPS_ID.get(service_name, False)
    if not shop_id:
        return None

    session = Session()

    db_availabilities_with_no_images = (
        session.query(Availability)
        .join(Product)
        .filter(and_(Availability.shop_id == shop_id, Product.images == None))
        .all()
    )

    availability_list = []
    folders = os.listdir(f"{SHOPS_ABSOLUTE_PATH}/{service_name}")
    for availability in db_availabilities_with_no_images:
        dbPartNumbers = availability.product.product_part_numbers

        for index in dbPartNumbers:
            if index.part_number not in folders:
                continue
            availability_list.append({"url": availability.url})
            break
        continue
    
    session.close()

    logger.info(f"The shop {service_name} has a total of {len(availability_list)} availabilities without images")
    return availability_list

    
async def download_images_for_each_shop(service_name, logger, empty_folders):
    shops_scripts = {
        "ldlc": {ldlc: "async"},
        "aussar": {aussar: "async"},
        "casemod": {casemod: "async"},
        "coolmod": {coolmod: "async"},
        "neobyte": {neobyte: "async"},
        "versus gamers": {vsgamers: "async"},
        "speedler": {speedler: "async"},
        "izarmicro": {izarmicro: "async"},
    }
    
    module = shops_scripts.get(service_name.lower(), {})
    script = list(module.keys())[0]
    type_func = list(module.values())[0]

    if type_func == "sync":
        data = script.main(logger, empty_folders, only_download_images=True)
    elif type_func == "async":
        data = await script.main(logger, empty_folders, only_download_images=True)
    else:
        return

    return

async def start(service_name, logger):
    if not logger:
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)
        logger.propagate = False

    t0 = datetime.now()
    logger.info(f"The Scrape of {service_name} for checking the images will start")

    availability_list = get_availabilities_with_empty_folders(service_name, logger)
    if not availability_list:
        logger.info(f"Sin directorios vacíos {availability_list}")
    else:
        await download_images_for_each_shop(service_name, logger, availability_list)

    availability_list = get_availabilities_without_images(service_name, logger)
    if not availability_list:
        logger.info(f"No hay disponibilidades sin imagenes {availability_list}")
    else:
        await download_images_for_each_shop(service_name, logger, availability_list)

    t1 = datetime.now()
    elapsed_time = float(round((t1 - t0).total_seconds() * 1000))
    logger.info(f"The Scrape of {service_name} for checking the images has finished - elapsed_time: {elapsed_time} ms")

    actual_time = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    client = InfluxDBClient(url=ev.INFLUXDB_URL, token=ev.INFLUXDB_TOKEN, org=ev.INFLUXDB_ORG)
    callback = BatchingCallback(logger=logger)
    write_api = client.write_api(write_options=SYNCHRONOUS, success_callback=callback.success, error_callback=callback.error, retry_callback=callback.retry)

    try:
        write_api.write(
            bucket=ev.INFLUXDB_BUCKET,
            record=[
                {
                    "measurement": "Images",
                    "tags": {"service": f"Check Images {service_name}"},
                    "fields": {"Elapsed time": elapsed_time},
                    "time": actual_time,
                }
            ],
        )

    except ReadTimeoutError as error:
        logger.error(f"ReadTimeoutError - Trace: {error}")
        pass

