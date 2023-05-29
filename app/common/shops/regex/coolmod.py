import logging
import re

import lxml.html
import pandas as pd
import ujson

from app.shared.auxiliary.functions import parse_number

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.propagate = False

FLOAT_INTEGER_REGEX = r"[-+]?(?:\d*\.\d+|\d+)"
SCALE_REGEX = "mm|cm|centimeter|milimeter"
GPU_SIZE_WORDS = "Dimensiones|Dimensions|Card Length|Largo de Tarjeta|dimensión|Tamaño de la tarjeta|Tarjeta"
GPU_POWER = "PSU recomendada|Recommended PSU|fuente de poder|Recommended Power Supply|alimentación mínima|alimentación recomendada|Fuente de alimentación"


def scrape_category(response, product, category):
    description = response.cssselect("div.productdetailinfocontainer.smoothshadow")[0]
    specs = description.xpath(".//li//text()")
    if len(specs) == 0:
        specs = description.xpath(".//ul//li//text()")

    #
    if category == "GPU":
        return product
        dimensions = []
        recommended_power = False
        for data in specs:
            result = re.findall(GPU_SIZE_WORDS, data, re.IGNORECASE)
            if result:
                dimensions.append(data)

            result = re.findall(GPU_POWER, data, re.IGNORECASE)
            if result:
                recommended_power = data

        logger.warning(f"dimensions: {dimensions} - recommended_power: {recommended_power}")
        final_dimension = False
        if len(dimensions) == 0:
            return False
        elif len(dimensions) == 1:
            final_dimension = dimensions[0]
        elif len(dimensions) > 1:
            for index in range(len(dimensions)):
                data = dimensions[index]
                result = re.findall("sin soporte|without Bracket", data, re.IGNORECASE)
                if result:
                    final_dimension = data
                    break

        if not final_dimension:
            return False

        content = final_dimension.replace(" ", "").replace(",", ".").lower()
        dimensions = re.findall(FLOAT_INTEGER_REGEX, content, re.IGNORECASE)
        scale = re.findall(SCALE_REGEX, content, re.IGNORECASE)
        if not scale or len(scale) == 0:
            return False

        millimeters = True
        if scale[0] == "cm" or scale[0] == "centimeter":
            millimeters = False

        updated_dimensions = []
        if len(dimensions) == 6:
            for index in range(len(dimensions)):
                if float(dimensions[index]) > 15 and millimeters:
                    updated_dimensions.append(dimensions[index])
        else:
            updated_dimensions = dimensions

        if len(updated_dimensions) != 3:
            return False

        new_dimensions = []
        for value in updated_dimensions:
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

        if recommended_power:
            power = re.findall("\d+", recommended_power, re.IGNORECASE)[0]
            product["PSU Power"] = power + " W"

    else:
        pass

    return product
