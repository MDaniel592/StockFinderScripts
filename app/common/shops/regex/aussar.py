import logging
import re

import lxml.html
import pandas as pd
import ujson

from app.shared.auxiliary.functions import parse_number

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.propagate = False


def scrape_category(response, product, category):
    try:
        data = response.xpath("(//div[@id='product-details'])/@data-product")[0]
        data = ujson.loads(data)
        html_description = data["description"]
        html_description = lxml.html.fromstring(html_description)
    except:
        return False

    items_list = html_description.xpath("//li/text()")
    logger.warning(items_list)
    #
    if category == "Chassis":
        return False
    elif category == "CPU Cooler":
        return False
    elif category == "GPU":
        return product
        for data in items_list:
            data_list = data.split(":")
            if len(data_list) != 2:
                continue

            title = data_list[0]
            content = data_list[1]
            if not title or not content:
                continue

            if title == "Dimensiones":
                millimeters = True
                content = content.replace(" ", "")
                dimensions = re.findall("\d+.\d+x\d+.\d+x\d+.\d+mm", content, re.IGNORECASE)
                if len(dimensions) == 0:
                    dimensions = re.findall("\d+x\d+x\d+mm", content, re.IGNORECASE)
                if len(dimensions) == 0:
                    dimensions = re.findall("\d+.\d+x\d+.\d+x\d+.\d+cm", content, re.IGNORECASE)
                    millimeters = False
                if len(dimensions) == 0:
                    dimensions = re.findall("\d+x\d+x\d+cm", content, re.IGNORECASE)
                    millimeters = False

                logger.warning(dimensions)
                dimensions = dimensions[0].split("x")
                if len(dimensions) != 3:
                    return False

                new_dimensions = []
                for value in dimensions:
                    value = re.findall("\d+,\d+|\d+,\d+|\d+.\d+|\d+.\d+|\d+", value, re.IGNORECASE)[0]
                    value = value if millimeters else parse_number(value) * 10
                    value = round(parse_number(value), 1)
                    new_dimensions.append(value)

                length = max(new_dimensions)
                height = min(new_dimensions)
                width = list(set(new_dimensions) - set([length, height]))[0]

                product["Longitud"] = str(length) + " mm"
                product["Anchura"] = str(width) + " mm"
                product["Altura"] = str(height) + " mm"
            elif title == "Fuente alimentación recomendada":
                power = re.findall("\d+.\d+|\d+,\d+|\d+,\d+|\d+", content, re.IGNORECASE)[0]
                product["PSU Power"] = power + " W"
            elif title == "Fan":
                product["Fan"] = content

    else:
        pass

    return product
