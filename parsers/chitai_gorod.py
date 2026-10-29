import re

from http_client import get_html
from parsers.base import BaseParser, PriceNotFound
from price_finder import is_product, json_from_html

# цена и название в микроразметке: <meta itemprop="price" content="599">
PRICE_TAG_RE = re.compile(r'itemprop="price"[^>]*content="([\d.,\s]+)"|content="([\d.,\s]+)"[^>]*itemprop="price"')
NAME_TAG_RE = re.compile(r'itemprop="name"[^>]*content="([^"]+)"')
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)


class ChitaiGorodParser(BaseParser):
    # ссылки вида /product/nazvanie-knigi-1234567, id берет общий парсер (последнее число)
    name = "chitai_gorod"
    title = "Читай-город"
    domains = ["chitai-gorod.ru"]

    def load(self, url):
        html = get_html(url)

        # 1) разметка schema.org в json (ld+json).
        # остальной json на странице не смотрим: там под ключом price
        # бывают служебные номера, а не цена
        products = [b for b in json_from_html(html) if is_product(b)]
        if products:
            return products

        # 2) та же разметка, но в виде атрибутов itemprop прямо в html
        m = PRICE_TAG_RE.search(html)
        if m:
            name = NAME_TAG_RE.search(html) or H1_RE.search(html)
            title = re.sub(r"<[^>]+>", "", name.group(1)).strip() if name else None
            return [{"price": m.group(1) or m.group(2), "name": title}]

        raise PriceNotFound(f"данные о товаре на странице не найдены (размер страницы {len(html)} символов)")
