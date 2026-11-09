import html as html_lib
import json
import re

from parsers.base import BaseParser, PriceNotFound
from price_finder import is_product, json_from_html

# блоки страницы озона хранят свои данные в атрибуте data-state:
# <div id="state-webPrice-3121879-default-1" data-state="{&quot;price&quot;:&quot;2 390 ₽&quot;...}">
WIDGET_RE = re.compile(r'<div\b[^>]*\bid="state-(webPrice|webProductHeading)-[^"]*"[^>]*>')
DATA_RE = re.compile(r'data-state="([^"]*)"')


class OzonParser(BaseParser):
    name = "ozon"
    title = "Ozon"
    domains = ["ozon.ru"]
    use_browser = True   # обычному запросу озон отвечает 403

    def get_product_id(self, url):
        # ссылки вида /product/naushniki-123456789/
        m = re.search(r"/product/(?:[^/]*-)?(\d+)", url)
        return m.group(1) if m else None

    def parse(self, page):
        blocks = []

        # 1) блок с ценой (webPrice) и блок с названием (webProductHeading).
        # берем только их, чтобы не схватить цену из рекомендаций.
        # в webPrice "price" - обычная цена, "cardPrice" - с Ozon Картой
        widgets = {}
        for tag in WIDGET_RE.finditer(page):
            data = DATA_RE.search(tag.group(0))
            if data and tag.group(1) not in widgets:
                try:
                    widgets[tag.group(1)] = json.loads(html_lib.unescape(data.group(1)))
                except ValueError:
                    pass
        if "webPrice" in widgets:
            # название ставим первым, чтобы find_title нашел именно его
            blocks.append({k: widgets[k] for k in ("webProductHeading", "webPrice") if k in widgets})

        # 2) запасной вариант - разметка schema.org
        blocks += [b for b in json_from_html(page) if is_product(b)]

        if not blocks:
            raise PriceNotFound(f"на странице нет блока с ценой (размер страницы {len(page)} символов)")
        return blocks
