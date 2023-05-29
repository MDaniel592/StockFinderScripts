import logging
import re

import lxml.html
import pandas as pd

from app.shared.auxiliary.functions import parse_number

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.propagate = False


def scrape_category(response, product, category):
    try:
        specs_table = response.xpath("//table[@id='product-parameters']")
        table = lxml.html.tostring(specs_table[0])
        df = pd.read_html(table)[0]
        #
        if category == "Chassis":
            row_gpu_max_len = df.loc[df[1] == "Longitud máx. tarjeta gráfica"]
            gpu_max_len = row_gpu_max_len.iloc[0, 2]

            row_cpu_max_len = df.loc[df[1] == "Altura máx. ventilador CPU"]
            cpu_max_len = row_cpu_max_len.iloc[0, 2]

            row_format_mb = df.loc[df[1] == "Formato de placa base"]
            format_mb = row_format_mb[:][2].values.tolist()

            #
            cpu_len_float = parse_number(re.findall("\d+,\d+|\d+.\d+|\d+", cpu_max_len, re.IGNORECASE)[0])
            gpu_len_float = parse_number(re.findall("\d+,\d+|\d+.\d+|\d+", gpu_max_len, re.IGNORECASE)[0])

            if cpu_max_len.find("cm") != -1:
                cpu_len_float = cpu_len_float * 10
            cpu_max_len = str(round(cpu_len_float, 1)) + " mm"

            if gpu_max_len.find("cm") != -1:
                gpu_len_float = gpu_len_float * 10
            gpu_max_len = str(round(gpu_len_float, 1)) + " mm"

            logger.warning(cpu_max_len)
            logger.warning(gpu_max_len)
            product["Formato de placa base"] = format_mb
            product["Altura máx. ventilador CPU"] = cpu_max_len
            product["Longitud máx. tarjeta gráfica"] = gpu_max_len

        elif category == "CPU Cooler":
            row_cooler_max_len = df.loc[df[1] == "Altura (ventilador incluido)"]
            try:
                cooler_max_len = row_cooler_max_len.iloc[0, 2]
            except:
                logger.warning(f"No cooler_max_len {product}")
                return False
            logger.warning(cooler_max_len)

            row_cpu_support = df.loc[df[1] == "Soporte del procesador"]
            try:
                cpu_support = row_cpu_support[:][2].values.tolist()
            except:
                logger.warning(f"No cpu_support {product}")
                return False

            logger.warning(cpu_support)

            row_liquid_cooler = df.loc[df[1] == "Tipo de refrigeración"]
            liquid_cooler = row_liquid_cooler.iloc[0, 2]
            logger.warning(liquid_cooler)

            liquid_cooler = re.findall("Kit de refrigeración|kit de refrigeracion|Watercooling|líquida|liquida|agua", liquid_cooler, re.IGNORECASE)
            liquid_cooler = True if len(liquid_cooler) != 0 else False

            if liquid_cooler == True:
                row_cooler_size = df.loc[df[1] == "Compatibilidad radiador AIO"]
                cooler_size = row_cooler_size.iloc[0, 2]
                logger.warning(cooler_size)
                product["Tamaño Radiador AIO"] = cooler_size

            cooler_max_len_float = parse_number(re.findall("\d+,\d+|\d+.\d+|\d+", cooler_max_len, re.IGNORECASE)[0])

            if cooler_max_len.find("cm") != -1:
                cooler_max_len_float = cooler_max_len_float * 10
            cooler_max_len = str(round(cooler_max_len_float, 1)) + " mm"

            product["Soporte Procesador"] = cpu_support
            product["Refrigeración Líquida"] = liquid_cooler
            product["Altura (ventilador incluido)"] = cooler_max_len
        elif category == "GPU":

            long = df.loc[df[1] == "Longitud"]
            long = long.iloc[0, 2]

            long_float = parse_number(re.findall("\d+,\d+|\d+.\d+|\d+", long, re.IGNORECASE)[0])

            if long.find("cm") != -1:
                long_float = long_float * 10
            long = str(round(long_float, 1)) + " mm"

            product["Longitud"] = long

            try:
                width = df.loc[df[1] == "Anchura"]
                width = width.iloc[0, 2]

                height = df.loc[df[1] == "Espesor"]
                height = height.iloc[0, 2]
            except:
                return product

            width_float = parse_number(re.findall("\d+,\d+|\d+.\d+|\d+", width, re.IGNORECASE)[0])
            height_float = parse_number(re.findall("\d+,\d+|\d+.\d+|\d+", height, re.IGNORECASE)[0])

            if width.find("cm") != -1:
                width_float = width_float * 10
            width = str(round(width_float, 1)) + " mm"

            if height.find("cm") != -1:
                height_float = height_float * 10
            height = str(round(height_float, 1)) + " mm"

            product["Anchura"] = width
            product["Altura"] = height

        else:
            pass
    except:
        return None

    return product
