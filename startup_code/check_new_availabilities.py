import logging
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
import app.shared.auxiliary.inputs as auxiliary_inputs
import app.shared.environment_variables as ev
import app.shared.error_messages as error_messages
import app.shared.valid_messages as valid_messages
from app.stockfinder_models.Alert import Alert
from app.stockfinder_models.Availability import Availability
from app.stockfinder_models.base import Base, Session, engine
from app.stockfinder_models.Build import Build
from app.stockfinder_models.Category import Category
from app.stockfinder_models.Manufacturer import Manufacturer
from app.stockfinder_models.Message import Message
from app.stockfinder_models.NewAvailability import NewAvailability
from app.stockfinder_models.NewAvailabilityChannels import NewAvailabilityChannels
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


async def check_availabilities(logger, service_name, channels):
    shops_scripts = {
        "ldlc": {ldlc: "async"},
        "aussar": {aussar: "async"},
        "casemod": {casemod: "async"},
        "coolmod": {coolmod: "async"},
        "neobyte": {neobyte: "async"},
        "vsgamers": {vsgamers: "async"},
        "speedler": {speedler: "async"},
        "izarmicro": {izarmicro: "async"},
    }

    # Limit 5 products for shop each run
    max_products = 5

    for unused in range(1):
        if service_name == "Versus Gamers":
            service_name = "vsgamers"

        session = Session()

        if channels:
            availabilities_db = (
                session.query(NewAvailabilityChannels)
                .filter(
                    and_(
                        NewAvailabilityChannels.processed == False,
                        NewAvailabilityChannels.invalid == False,
                        NewAvailabilityChannels.counter != 3,
                    )
                )
                .all()
            )

        else:
            availabilities_db = (
                session.query(NewAvailability)
                .filter(
                    and_(
                        NewAvailability.processed == False,
                        NewAvailability.invalid == False,
                        NewAvailability.counter != 3,
                    )
                )
                .all()
            )

        if not availabilities_db:
            session.close()
            break

        availabilities = {}
        for availability in availabilities_db:
            availability_dict = availability.__dict__
            shop_name = auxiliary_inputs.get_shop_from_url(availability_dict["url"])
            if shop_name == "Unknown":
                availability.processed = True
            elif shop_name == service_name.lower():
                aval_result = session.query(Availability).filter(Availability.url == availability_dict["url"]).first()
                if not channels and aval_result:
                    # Si la disponibilidad ya existiese, se añade la alerta al usuario
                    #
                    user_id = availability_dict["user_id"]
                    max_price = availability_dict["max_price"]
                    alert_by_email = availability_dict["alert_by_email"]
                    alert_by_telegram = availability_dict["alert_by_telegram"]
                    #
                    alert = Alert(
                        user_id=user_id,
                        availability=aval_result,
                        max_price=max_price,
                        alert_by_telegram=alert_by_telegram,
                        alert_by_email=alert_by_email,
                    )
                    session.add(alert)
                    availability.processed = True
                    continue
                elif aval_result:
                    logger.warning("La disponibilidad ya existe")
                    availability.processed = True
                    continue

                if not availabilities.get(shop_name, None):
                    availabilities[shop_name] = []

                if len(availabilities[shop_name]) == max_products:
                    break

                if channels:
                    temp_dict = {
                        "_id": availability_dict["_id"],
                        "url": availability_dict["url"],
                        "counter": availability_dict["counter"],
                    }
                else:
                    temp_dict = {
                        "_id": availability_dict["_id"],
                        "url": availability_dict["url"],
                        "user_id": availability_dict["user_id"],
                        "counter": availability_dict["counter"],
                        "max_price": availability_dict["max_price"],
                        "alert_by_email": availability_dict["alert_by_email"],
                        "alert_by_telegram": availability_dict["alert_by_telegram"],
                    }

                availabilities[shop_name].append(temp_dict)

            else:
                continue

        session.commit()
        if not availabilities:
            session.close()
            break

        for shop in availabilities:
            module = shops_scripts.get(shop, {})
            script = list(module.keys())[0]
            type_func = list(module.values())[0]

            if type_func == "sync":
                data = script.main(logger, availabilities[shop])
            elif type_func == "async":
                data = await script.main(logger, availabilities[shop])
            else:
                break

            if len(data) == 0:
                continue
            for product in data:
                logger.warning(product)

                if channels:
                    result = product.get("result", {})
                    counter = int(product["counter"]) + 1
                    new_avai_chan_id = int(product["_id"])
                    #
                    error_flag = result.get("error", False)
                    if error_flag == False:
                        session.query(NewAvailabilityChannels).filter(NewAvailabilityChannels._id == new_avai_chan_id).update(
                            {"counter": counter, "processed": True},
                            synchronize_session=False,
                        )
                        session.commit()
                        continue

                    table_update = {
                        "counter": counter,
                        "name": result.get("name", None),
                        "code": result.get("code", None),
                        "category": result.get("category", None),
                        "part_number": result.get("part_number", None),
                        "manufacturer": result.get("manufacturer", None),
                        "error_message": result.get("error_message", None),
                    }

                    if result.get("error_message", None) == error_messages.SPECS_NOT_FOUND or counter == 3:
                        table_update["invalid"] = True

                    session.query(NewAvailabilityChannels).filter(NewAvailabilityChannels._id == new_avai_chan_id).update(
                        table_update, synchronize_session=False
                    )
                    session.commit()
                    continue

                else:
                    url = product["url"]
                    user_id = product["user_id"]
                    max_price = product["max_price"]
                    new_avai_id = int(product["_id"])
                    counter = int(product["counter"]) + 1
                    alert_by_email = product["alert_by_email"]
                    alert_by_telegram = product["alert_by_telegram"]

                    success = product.get("result", False)
                    #
                    if success != True:
                        table_update = {
                            "counter": counter,
                            "invalid": True if counter == 3 else False,
                        }

                        session.query(NewAvailability).filter(NewAvailability._id == new_avai_id).update(table_update, synchronize_session=False)
                        session.commit()
                        continue
                    #
                    availability = session.query(Availability).filter(Availability.url == url).first()
                    alert = Alert(
                        user_id=user_id,
                        availability=availability,
                        max_price=max_price,
                        alert_by_telegram=alert_by_telegram,
                        alert_by_email=alert_by_email,
                    )

                    session.add(alert)
                    session.query(NewAvailability).filter(NewAvailability._id == new_avai_id).update(
                        {"counter": counter, "processed": True},
                        synchronize_session=False,
                    )
                    session.commit()
                    continue

        session.close()

    return None


# COLISION
# Puede haber duplicidades de entradas para una misma disponibilidad
# En el usuario comprobamos nuevamente si la disponibilidad existe
async def start(service_name, logger=None):
    if not logger:
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)
        logger.propagate = False

    t0 = datetime.now()
    logger.info(f"The Scrape of {service_name} for checking the availability will start")

    await check_availabilities(logger, service_name, channels=True)
    await check_availabilities(logger, service_name, channels=False)

    t1 = datetime.now()
    elapsed_time = float(round((t1 - t0).total_seconds() * 1000))
    logger.info(f"The Scrape of {service_name} has finished - elapsed_time: {elapsed_time} ms")

    actual_time = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    client = InfluxDBClient(url=ev.INFLUXDB_URL, token=ev.INFLUXDB_TOKEN, org=ev.INFLUXDB_ORG)
    callback = BatchingCallback(logger=logger)
    write_api = client.write_api(write_options=SYNCHRONOUS, success_callback=callback.success, error_callback=callback.error, retry_callback=callback.retry)

    try:
        write_api.write(
            bucket=ev.INFLUXDB_BUCKET,
            record=[
                {
                    "measurement": "Availability",
                    "tags": {"service": f"Check Availability {service_name}"},
                    "fields": {"Elapsed time": elapsed_time},
                    "time": actual_time,
                }
            ],
        )

    except ReadTimeoutError as error:
        logger.error(f"ReadTimeoutError - Trace: {error}")
        pass
