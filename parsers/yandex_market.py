import re

from parsers.base import BaseParser


class YandexMarketParser(BaseParser):
    # цену берем из разметки schema.org на странице товара, это делает общий парсер.
    # обычные запросы маркет часто встречает капчей, поэтому открываем в браузере
    name = "yandex_market"
    title = "Яндекс Маркет"
    domains = ["market.yandex.ru"]
    use_browser = True

    def get_product_id(self, url):
        # бывают ссылки /product--название/123 и /card/название/123
        m = re.search(r"/(?:product--[^/]+|card/[^/]+)/(\d+)", url)
        return m.group(1) if m else super().get_product_id(url)
