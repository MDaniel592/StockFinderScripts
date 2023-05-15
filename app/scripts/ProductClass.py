from typing import Optional
from xmlrpc.client import boolean


class Product:
    def __init__(
        self,
        name: str = None,
        short_name: str = None,
        part_number: str = None,
        images: dict = None,
        category: str = None,
        manufacturer: str = None,
        #
        code: int = -1,
        url: str = None,
        shop_name: str = None,
        description: str = None,
        error_message: str = None,
        #
        price: float = -1,
        stock: bool = 0,
    ):
        self.name = name
        self.short_name = short_name
        self.part_number = part_number
        self.images = images
        self.category = category
        self.manufacturer = manufacturer

        self.code = code
        self.url = url
        self.shop_name = shop_name
        self.description = description
        self.error_message = error_message

        self.price = price
        self.stock = stock


new_product = Product(name="A")

print(getattr(new_product, "name", False))
