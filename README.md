# StockFinder Scripts

Scripts used for updating prices and stock. Additionally, newer products which are valid components will be added to the DB

## Considerations
- The 'utils' module contains:
    - shared_variables file with absolute paths + INFLUXDB TOKEN, ORG and BUCKET + variables
    - auxiliary functions for parsing products, adding the products to the DB, etc...

## Requirements
- Proxies. The project is using Proxys from the Oracle Kubernetes Cluster
- Postgresql database. The DB stores all the product's data 
- InfluxDB. The DB stores the performance metrics of each script executed

## Folders
- app: where all the code is located
- startup_code: the scripts located on this folder are called from 'check_shop' script whic is always active (while True)

## ¿Cómo funciona?

Básicamente los dos tipos de scripts más importantes son 'stock' y 'product'

### Stock

Con estos scripts se consulta el stock de los productos, pero se hace de forma que se consultan muchos products con una única consulta (request). Sin embargo, el part number no está en estas respuestas, por lo que el script SOLO puede comprobar el stock y si la disponibilidad existe en la DB. Cuando se reciben todos los productos, se tienen dos situaciones:

- Si hay part number
    - Se intenta identificar el producto y añadirlo a la DB si cumple todos los requisitos.

- No hay part number o no se ha podido añadir el producto y/o la disponibilidad aún cumpliendo los requisitos
    - Se añade esta disponibilidad a una tabla intermedia para identificar el producto y añadirlo a la base de datos con el script 'Product'

### Product

Este script se encarga de identificar el producto de forma individual. Extrae toda la información necesaria del producto y lo registra en la DB si cumple las condiciones predefinidas

### Startup

- 'check_shop' se encarga de llamar a los scripts. Adicionalmente, hay un script check_unupdated que marca sin stock los productos que llevan sin actualizarse 24 horas.