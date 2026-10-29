import json
import re
from urllib.parse import urlparse

from http_client import get_json
from parsers.base import BaseParser

# html-страница озона почти пустая, данные приходят отдельным запросом сюда
# (его видно в DevTools -> Network)
API_URL = "https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2"


class OzonParser(BaseParser):
    name = "ozon"
    title = "Ozon"
    domains = ["ozon.ru"]

    def get_product_id(self, url):
        # ссылки вида /product/naushniki-123456789/
        m = re.search(r"/product/(?:[^/]*-)?(\d+)", url)
        return m.group(1) if m else None

    def load(self, url):
        path = urlparse(url).path
        return [get_json(API_URL, params={"url": path})]

    def cut(self, data):
        # в widgetStates лежат все блоки страницы, каждый записан строкой с json.
        # берем только цену (webPrice) и название (webProductHeading),
        # иначе можно схватить цену из рекомендаций
        if not isinstance(data, dict):
            return data
        result = {}
        for key, value in data.get("widgetStates", {}).items():
            if key.startswith(("webPrice", "webProductHeading")):
                try:
                    result[key] = json.loads(value)
                except (ValueError, TypeError):
                    pass
        return result or data
