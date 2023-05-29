import os
import typing
from datetime import datetime

from influxdb_client import InfluxDBClient
from influxdb_client.client.exceptions import InfluxDBError
from influxdb_client.client.write_api import SYNCHRONOUS
from urllib3.exceptions import ReadTimeoutError

import app.scripts.stock.stock_aussar as stock_aussar
import app.scripts.stock.stock_casemod as stock_casemod
import app.scripts.stock.stock_coolmod as stock_coolmod
import app.scripts.stock.stock_izarmicro as stock_izarmicro
import app.scripts.stock.stock_ldlc as stock_ldlc
import app.scripts.stock.stock_neobyte as stock_neobyte
import app.scripts.stock.stock_nvidia_api as stock_nvidia_api
import app.scripts.stock.stock_speedler as stock_speedler
import app.scripts.stock.stock_vsgamers as stock_vsgamers
import app.shared.environment_variables as ev

MODULES_DICT = {
    "Aussar": {"module": stock_aussar, "async": True},
    "Casemod": {"module": stock_casemod, "async": True},
    "Coolmod": {"module": stock_coolmod, "async": True},
    "IzarMicro": {"module": stock_izarmicro, "async": True},
    "LDLC": {"module": stock_ldlc, "async": True},
    "Neobyte": {"module": stock_neobyte, "async": True},
    "Nvidia": {"module": stock_nvidia_api, "async": True},
    "Speedler": {"module": stock_speedler, "async": True},
    "Versus Gamers": {"module": stock_vsgamers, "async": True},
}


class BatchingCallback(object):
    def __init__(self, logger):
        self.logger = logger

    def success(self, conf: typing.Tuple[str, str, str], data: str):
        self.logger.info(f"Written batch: {conf}, data: {data}")

    def error(self, conf: typing.Tuple[str, str, str], data: str, exception: InfluxDBError):
        self.logger.error(f"Cannot write batch: {conf}, data: {data} due: {exception}")

    def retry(self, conf: typing.Tuple[str, str, str], data: str, exception: InfluxDBError):
        self.logger.warning(f"Retryable error occurs for batch: {conf}, data: {data} retry: {exception}")


async def start(service_name, logger, category=[]):
    t0 = datetime.now()
    logger.info(f"The Scrape of {service_name} for checking the stock will start - category: {category}")

    module_selected = MODULES_DICT.get(service_name).get("module")
    async_func = MODULES_DICT.get(service_name).get("async")

    if async_func:
        await module_selected.main(category_selected=category, logger=logger)
    else:
        module_selected.main(category_selected=category, logger=logger)

    t1 = datetime.now()
    elapsed_time = float(round((t1 - t0).total_seconds() * 1000))
    logger.info(f"The Scrape of {service_name} has finished - elapsed_time: {elapsed_time} ms")

    actual_time = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    tag_name = f"Check Stock {service_name}"
    if len(category) != 0:
        for value in category:
            tag_name += f" {value}"

    client = InfluxDBClient(url=ev.INFLUXDB_URL, token=ev.INFLUXDB_TOKEN, org=ev.INFLUXDB_ORG)
    callback = BatchingCallback(logger=logger)
    write_api = client.write_api(write_options=SYNCHRONOUS, success_callback=callback.success, error_callback=callback.error, retry_callback=callback.retry)

    try:
        write_api.write(
            bucket=ev.INFLUXDB_BUCKET,
            record=[
                {
                    "measurement": "Stock",
                    "tags": {"service": tag_name},
                    "fields": {"Elapsed time": elapsed_time},
                    "time": actual_time,
                }
            ],
        )
    except ReadTimeoutError as error:
        logger.error(f"ReadTimeoutError - Trace: {error}")
        pass
