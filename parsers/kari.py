from parsers.base import BaseParser


class KariParser(BaseParser):
    # данные о товаре лежат прямо в странице, поэтому хватает общего парсера
    name = "kari"
    title = "Kari"
    domains = ["kari.com"]
