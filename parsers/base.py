import re
from urllib.parse import urlparse

from ai import AIUnavailable, ask_ai
from browser import get_html_browser
from config import USE_AI
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
    use_browser = False   # True - открывать страницу в браузере, а не обычным запросом

    @classmethod
    def can_handle(cls, url):
        host = urlparse(url).netloc.lower()
        return any(host == d or host.endswith("." + d) for d in cls.domains)

    def get_product_id(self, url):
        # по умолчанию берем последнее длинное число из ссылки
        numbers = re.findall(r"\d{5,}", urlparse(url).path)
        return numbers[-1] if numbers else None

    def download(self, url):
        # некоторые сайты не отдают страницу обычному запросу, для них открываем браузер
        if self.use_browser:
            return get_html_browser(url)
        return get_html(url)

    def parse(self, html):
        # вытаскиваем из страницы json, где может быть цена
        return json_from_html(html)

    def cut(self, data):
        # здесь можно оставить только ту часть json, где описан сам товар
        return data

    def find_in_page(self, html):
        blocks = self.parse(html)
        if not blocks:
            raise PriceNotFound("на странице нет json с данными")

        for block in blocks:
            data = self.cut(block)
            price = find_price(data)
            if price:
                return price, find_title(data)

        raise PriceNotFound("цена не найдена")

    def get_price(self, url):
        html = self.download(url)
        try:
            return self.find_in_page(html)
        except PriceNotFound as error:
            if not USE_AI:
                raise
            # обычный код цену не нашел - просим ИИ прочитать страницу
            print("    цена не найдена обычным способом, спрашиваем ИИ...")
            try:
                result = ask_ai(html)
            except AIUnavailable as e:
                raise PriceNotFound(f"{error}; {e}")
            if not result:
                raise PriceNotFound(f"{error}; ИИ тоже не нашел цену")
            print("    цену нашел ИИ")
            return result
