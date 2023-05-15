import asyncio
import logging
import random
import sys

from startup_code import check_new_availabilities, check_stock

SLEEP_TIME = 10  # Minutes


async def main(service_name):

    logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
    logger = logging.getLogger(service_name)

    counter = -1
    while True:

        category = ["GPU", "CPU"]
        if service_name == "Coolmod":
            category = ["GPU", "CPU", "Reaco"]

        await check_stock.start(service_name=service_name, logger=logger, category=category)
        await asyncio.sleep(random.randint(10, 30))

        await check_new_availabilities.start(service_name=service_name, logger=logger)
        await asyncio.sleep(random.randint(10, 30))

        if counter == -1 or counter == 20:
            await check_stock.start(service_name=service_name, logger=logger)
            counter = 0

        await asyncio.sleep(60 * SLEEP_TIME)
        counter += 1


if __name__ == "__main__":
    service_name = str(sys.argv[1])
    asyncio.run(main(service_name))
