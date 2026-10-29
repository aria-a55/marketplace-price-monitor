import re
from urllib.parse import urlparse

from http_client import get_html
from price_finder import find_price, find_title, json_from_html


class PriceNotFound(Exception):
    pass


class BaseParser:
    """Общий парсер. Магазины наследуются от него и переопределяют
    только то, что у них устроено по-другому."""

    name = ""      # как магазин записывается в базу
    title = ""     # как показывать пользователю
    domains = []

    @classmethod
    def can_handle(cls, url):
        host = urlparse(url).netloc.lower()
        return any(host == d or host.endswith("." + d) for d in cls.domains)

    def get_product_id(self, url):
        # по умолчанию берем последнее длинное число из ссылки
        numbers = re.findall(r"\d{5,}", urlparse(url).path)
        return numbers[-1] if numbers else None

    def load(self, url):
        # скачиваем страницу и вытаскиваем из нее json
        return json_from_html(get_html(url))

    def cut(self, data):
        # здесь можно оставить только ту часть json, где описан сам товар
        return data

    def get_price(self, url):
        blocks = self.load(url)
        if not blocks:
            raise PriceNotFound("на странице нет json с данными")

        for block in blocks:
            data = self.cut(block)
            price = find_price(data)
            if price:
                return price, find_title(data)

        raise PriceNotFound("цена не найдена")
