import logging
import re

import lxml.html

import app.shared.auxiliary.inputs as auxiliary_inputs
from app.shared.auxiliary.functions import parse_number

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.propagate = False

NUMBER_REGEX = "\d+,\d+|\d+,\d+|\d+"

CASE_CPU_REGEX = f"(?:CPU):.+?(?:\d+,\d+|\d+,\d+|\d+).+?(?:cm|mm)|(?:CPU).+?(?:\d+,\d+|\d+,\d+|\d+).+?(?:cm|mm)|(?:CPU).+?(\d+,\d+|\d+,\d+|\d+).+?(?:cm|mm)"
CASE_GPU_REGEX = f"(?:gráfica|GPU|gráficos|VGA):.+?(?:\d+,\d+|\d+,\d+|\d+).+?(?:cm|mm)|(?:gráfica|GPU|gráficos|VGA).+?(?:\d+,\d+|\d+,\d+|\d+).+?(?:cm|mm)|(?:GPU).*(\d+,\d+|\d+,\d+|\d+).+?(?:cm|mm)"
CASE_MB_ATX_REGEX = f"(?:tarjeta madre|placa base|Factor de forma|factor de forma).+( ATX|,ATX)"
CASE_MB_MicroATX_REGEX = f"(?:tarjeta madre|placa base|Factor de forma|factor).+( Micro|,Micro|M-ATX)"
CASE_MB_MiniITX_REGEX = f"(?:tarjeta madre|placa base|Factor de forma|factor).+( ITX|,ITX|-ITX)"
#
CPU_COOLER_HEIGHT_REGEX = "(?:Altura:).+?(?:\d+,\d+|\d+,\d+|\d+).+?(?:cm|mm)"
CPU_COOLER_SIZE_REGEX = "(?:Tamaño producto).+?(?:\d+,\d+|\d+,\d+|\d+).+?(?:cm|mm)"
CPU_COOLER_RADIATOR_REGEX = "(?:Altura).+?(?:radiador).+?(?:\d+,\d+|\d+,\d+|\d+).+?(?:cm|mm)"
CPU_COOLER_BOMBA_REGEX = "(?:Dimensaiones bomba).+?(?:\d+,\d+|\d+,\d+|\d+).+?(?:cm|mm)"
#
FLOAT_INTEGER_REGEX = r"[-+]?(?:\d*\.\d+|\d+)"
SCALE_REGEX = "mm|cm|centimeter|milimeter"
GPU_POWER = "PSU recomendada|Recommended PSU|fuente de poder|Recommended Power Supply|alimentación mínima|alimentación recomendada|Fuente de alimentación|greater power supply"
GPU_SIZE_WORDS = "Profundidad:|Altura:|Ancho:"
GPU_SIZE_COMPLETED = "Dimensiones|Dimensions|Card Dimension|Card Length|Largo de Tarjeta|dimensión|Tamaño de la tarjeta"


SOCKET_AMD_LIST = ["AM3", "AM3+", "AM4", "AM5", "TR4"]
SOCKET_INTEL_LIST = ["1151", "1150", "1155", "1156", "2011", "2066", "1700", "1200"]
a, b = "ÁáÉéÍíÓóÚúü", "AaEeIiOoUuu"
trans = str.maketrans(a, b)


def scrape_category(response, product, category, original_category):
    #
    if category == "GPU":
        return product
        description = response.xpath("//div[@id='ficha-producto-caracteristicas']")
        if not description:
            return False
        description = description[0]

        specs_data = description.xpath(".//ul/li//text()")
        dimensions_A = []
        dimensions_B = []
        scale_A = None
        scale_B = None
        recommended_power = False

        for data in specs_data:
            result = re.findall(GPU_SIZE_WORDS, data, re.IGNORECASE)
            if result:
                result = re.findall(FLOAT_INTEGER_REGEX, data, re.IGNORECASE)
                if result:
                    dimensions_A.append(result[0])
                    scale_A = re.findall(SCALE_REGEX, data, re.IGNORECASE)[0]

            result = re.findall(GPU_SIZE_COMPLETED, data, re.IGNORECASE)
            if result:
                new_data = data.split("x")
                for value in new_data:
                    result = re.findall(FLOAT_INTEGER_REGEX, value, re.IGNORECASE)
                    if result:
                        dimensions_B.append(result[0])
                        scale_B = re.findall(SCALE_REGEX, data, re.IGNORECASE)[0]

            result = re.findall(GPU_POWER, data, re.IGNORECASE)
            if result:
                recommended_power = data

        dimensions = dimensions_A if len(dimensions_A) > len(dimensions_B) else dimensions_B
        if scale_A and scale_B:
            scale = scale_A if len(dimensions_A) > len(dimensions_B) else scale_B
        elif scale_A and not scale_B:
            scale = scale_A
        elif not scale_A and scale_B:
            scale = scale_B
        else:
            return False

        logger.warning(f"dimensions: {dimensions} - recommended_power: {recommended_power} - scale: {scale}")
        millimeters = True
        if scale == "cm" or scale == "centimeter":
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
            power = re.findall("\d+", recommended_power, re.IGNORECASE)
            if power:
                product["PSU Power"] = power[0] + " W"

    elif category == "Chassis":
        specs_data = response.cssselect("#ficha-producto-caracteristicas")[0].text_content()
        specs_data = " ".join(specs_data.split())

        ####
        # CPU
        ####
        match = re.search(CASE_CPU_REGEX, specs_data, re.IGNORECASE)
        if not match:
            logger.warning(f"1. Sin Altura de CPU {product}")
            return False
        match = match[0]

        unit = None
        if match.find("cm") != -1:
            unit = "cm"
        else:
            unit = "mm"

        cpu_len = re.findall(NUMBER_REGEX, match, re.IGNORECASE)
        if not cpu_len:
            logger.warning(f"2. Sin Altura de CPU {product}")
            return False
        cpu_len = parse_number(cpu_len[0])

        if unit == "cm":
            cpu_len = cpu_len * 10
        cpu_len = str(round(cpu_len, 1)) + " mm"

        ####
        # GPU
        ####
        match = re.search(CASE_GPU_REGEX, specs_data, re.IGNORECASE)
        if not match:
            logger.warning(f"1. Sin Longitud GPU {product}")
            return False
        match = match[0]

        unit = None
        if match.find("cm") != -1:
            unit = "cm"
        else:
            unit = "mm"

        gpu_len = re.findall(NUMBER_REGEX, match, re.IGNORECASE)
        if not gpu_len:
            logger.warning(f"2. Sin Longitud GPU {product}")
            return False
        gpu_len = parse_number(gpu_len[0])

        if unit == "cm":
            gpu_len = gpu_len * 10
        gpu_len = str(round(gpu_len, 1)) + " mm"

        ####
        # MB
        ####

        for unused in range(1):
            match = re.findall(CASE_MB_ATX_REGEX, specs_data, re.IGNORECASE)
            if match:
                logger.warning(f"La placa es ATX")
                form_factor = ["ATX", "Micro ATX", "Mini ITX"]
                break
            match = re.findall(CASE_MB_MicroATX_REGEX, specs_data, re.IGNORECASE)
            if match:
                logger.warning(f"La placa es Micro ATX")
                form_factor = ["Micro ATX", "Mini ITX"]
                break
            match = re.findall(CASE_MB_MiniITX_REGEX, specs_data, re.IGNORECASE)
            if match:
                logger.warning(f"La placa es Mini ITX")
                form_factor = ["Mini ITX"]
                break

            form_factor = ["ATX", "Micro ATX", "Mini ITX"]

        product["Formato de placa base"] = form_factor
        product["Altura máx. ventilador CPU"] = cpu_len
        product["Longitud máx. tarjeta gráfica"] = gpu_len

    elif category == "CPU Cooler":
        specs_data = response.cssselect("#ficha-producto-caracteristicas")[0].text_content()
        specs_data = " ".join(specs_data.split())

        original_category = auxiliary_inputs.fix_name_chars(original_category.upper().replace(" ", ""))
        original_category = original_category.translate(trans)
        liquid_cooler = True if original_category == "REFRIGERACIONLIQUIDA" else False
        if liquid_cooler:
            radiator_size = re.findall("\d\d\d", product["name"], re.IGNORECASE)
            if not radiator_size:
                logger.warning("No se identifica el tamaño del radiador")
                return False

            radiator_size = "Radiador " + str(int(radiator_size[0])) + " mm"

        for unused in range(1):
            match = re.search(CPU_COOLER_HEIGHT_REGEX, specs_data, re.IGNORECASE)
            if match:
                cpu_size = match[0]
                break
            match = re.search(CPU_COOLER_SIZE_REGEX, specs_data, re.IGNORECASE)
            if match:
                cpu_size = match[0]
                cpu_size = cpu_size.split("x")[2]
                break

            if liquid_cooler:
                match = re.search(CPU_COOLER_RADIATOR_REGEX, specs_data, re.IGNORECASE)
                if match:
                    cpu_size = match[0]
                    break
                match = re.search(CPU_COOLER_BOMBA_REGEX, specs_data, re.IGNORECASE)
                if match:
                    cpu_size = match[0]
                    break

            logger.warning("Sin altura")
            return False

        unit = None
        if cpu_size.find("cm") != -1:
            unit = "cm"
        else:
            unit = "mm"

        cpu_size = re.findall(NUMBER_REGEX, cpu_size, re.IGNORECASE)
        if not cpu_size:
            logger.warning(f"2. Sin Altura de CPU {product}")
            return False
        cpu_size = parse_number(cpu_size[0])

        if unit == "cm":
            cpu_size = cpu_size * 10
        cpu_size = str(round(cpu_size, 1)) + " mm"

        for unused in range(1):
            cpu_support = response.xpath("//strong[contains(text(),'compatibilidad')]/following-sibling::ul")
            if cpu_support:
                break

            cpu_support = response.xpath("//li[contains(text(),'procesador soportados')]")
            if cpu_support:
                break

            cpu_support = response.xpath("//li[contains(text(),'COMPATIBLE')]/..")
            if cpu_support:
                break

            logger.warning("Sin soporte")
            return False

        cpu_support_text = cpu_support[0].text_content()
        cpu_support_list = []
        for value in SOCKET_AMD_LIST:
            match = re.findall(value, cpu_support_text, re.IGNORECASE)
            if match:
                cpu_support_list.append(f"AMD {value}")

        for value in SOCKET_INTEL_LIST:
            match = re.findall(value, cpu_support_text, re.IGNORECASE)
            if match:
                cpu_support_list.append(f"Intel {value}")

        cpu_support_list.sort()

        if liquid_cooler:
            product["Refrigeración Líquida"] = liquid_cooler
            product["Tamaño Radiador AIO"] = radiator_size

        product["Soporte Procesador"] = cpu_support_list
        product["Altura (ventilador incluido)"] = cpu_size

    else:
        pass

    return product
