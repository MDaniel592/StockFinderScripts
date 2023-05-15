import app.database_functions as database_functions
import app.utils.error_messages as error
import app.utils.product_regex as product_regex
import app.utils.valid_messages as valid
from app.stockfinder_models.Availability import Availability
from app.stockfinder_models.base import Session
from app.stockfinder_models.NewAvailabilityChannels import NewAvailabilityChannels


def process_data(logger, update_products):
    if not update_products:
        logger.warning(error.PRODUCT_DATA_NOT_FOUND)
        return

    update_products_columns = ["price", "stock", "code", "shop_id"]
    equal_params = ["code", "shop_id"]

    if len(update_products) > 0:
        result = database_functions.update_multiple_row_availabilities(update_products_columns, update_products, equal_params)
        if result:
            logger.info(valid.DB_PRODUCTS_UPDATED)
        else:
            logger.error(error.DB_PRODUCTS_ERROR)

    return


def add_product(logger, shop_data, product, is_product=False, add_product=False, http_session=None, process_flag=True):

    code = product["code"]
    stock = product["stock"]
    price = product["price"]
    category = product["category"]
    #
    shop_id = shop_data["shop_id"]
    shop_name = shop_data["shop_name"]
    db_products_data = shop_data["shop_db_data"]

    if db_products_data.get(code, False) and price > 0:
        product_tuple = (price, stock, code, shop_id)
        logger.info(valid.product_stock_updated(stock, price, code))
        return True, product_tuple

    elif not db_products_data.get(code, False):
        
        url = product.get("url", None)
        url = url[:-1] if url[len(url) - 1] == "/" else url

        part_number = product.get("part_number", None)

        availability = {
            "url": url,
            "code": code,
            "price": price,
            "category": category,
            "part_number": part_number,
            "name": product.get("name", None),
            "refurbished": product.get("refurbished", False),
            "second_name": product.get("second_name", None),
            "description": product.get("description", None),
            "manufacturer": product.get("manufacturer", None),
        }

        logger.info(error.product_not_in_DB(availability))
        result = product_regex.validate_data(availability, is_product=is_product)
        if not result:
            return False, None

        msg = "la disponibilidad"
        result = False
        if process_flag == True and part_number:
            result = product_regex.process_product(availability, shop_name, 0, add_product=add_product)

        if not result or process_flag == False or not part_number:
            session = Session()
            result = session.query(NewAvailabilityChannels).filter(NewAvailabilityChannels.url == url).first()
            if result:
                session.close()
                return False, None

            logger.info(valid.product_valid(availability))
            channel_availability = NewAvailabilityChannels(url=url, shop_name=shop_name)
            session.add(channel_availability)
            session.commit()
            session.close()
            result = True

        if result:
            logger.info(f"Sí se ha añadido {msg}: {availability}")
        else:
            logger.error(f"No se ha añadido {msg}: {availability}")

    return False, None
