import json
import re

# ключи, под которыми обычно лежит текущая цена, по порядку важности
PRICE_KEYS = ["finalprice", "saleprice", "currentprice", "price", "lowprice"]

# если в ключе с "price" есть одно из этих слов, то это не текущая цена
# (oldPrice, originalPrice, priceBeforeDiscount и т.п.)
BAD_WORDS = ["old", "original", "base", "before", "crossed", "strike", "list",
             "high", "max", "credit", "installment", "month", "bonus",
             "delivery", "currency"]


def to_kopecks(value):
    """Переводит цену из json в копейки. Если это не цена, возвращает None."""
    if isinstance(value, bool):
        return None

    if isinstance(value, dict):
        # иногда цена записана так: {"value": 1299, "currency": "RUB"}
        for key in ("value", "amount", "price"):
            if key in value:
                return to_kopecks(value[key])
        return None

    if isinstance(value, (int, float)):
        rub = float(value)
    elif isinstance(value, str):
        # строки вида "1 299 ₽" или "1 299,90 руб."
        text = value.lower()
        for junk in ["₽", "руб.", "руб", "\xa0", " ", " ", " "]:
            text = text.replace(junk, "")
        text = text.replace(",", ".")
        if not re.fullmatch(r"\d+(\.\d{1,2})?", text):
            return None
        rub = float(text)
    else:
        return None

    if rub <= 0:
        return None
    return round(rub * 100)


def find_price(data):
    """Ищет текущую цену в json любой вложенности. Возвращает копейки или None."""
    found = []  # пары (номер ключа в PRICE_KEYS, цена)

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                k = str(key).lower()
                if "price" in k and any(word in k for word in BAD_WORDS):
                    continue  # старая цена, внутрь тоже не заходим
                if k in PRICE_KEYS:
                    price = to_kopecks(value)
                    if price:
                        found.append((PRICE_KEYS.index(k), price))
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str) and node.strip()[:1] in ("{", "["):
            # бывает, что внутри json лежит строка, в которой тоже json
            try:
                walk(json.loads(node))
            except ValueError:
                pass

    walk(data)
    if not found:
        return None

    # берем цену с самым важным ключом, а среди одинаковых - первую найденную.
    # самую маленькую не берем: она может быть из блока "похожие товары"
    found.sort(key=lambda pair: pair[0])
    return found[0][1]


def find_title(data):
    """Название товара - первая непустая строка под ключом name или title."""
    if isinstance(data, dict):
        for key in ("name", "title"):
            value = data.get(key)
            if isinstance(value, str) and value.strip() and not value.startswith("{"):
                return value.strip()
        for value in data.values():
            title = find_title(value)
            if title:
                return title
    elif isinstance(data, list):
        for item in data:
            title = find_title(item)
            if title:
                return title
    elif isinstance(data, str) and data.strip()[:1] == "{":
        try:
            return find_title(json.loads(data))
        except ValueError:
            pass
    return None


def is_product(item):
    """Это описание товара по schema.org? Книги часто размечают типом Book."""
    if not isinstance(item, dict):
        return False
    kind = item.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return "Product" in kinds or "Book" in kinds


SCRIPT_RE = re.compile(r"<script([^>]*)>(.*?)</script>", re.S | re.I)
STATE_RE = re.compile(r"window\.__(INITIAL_STATE|PRELOADED_STATE|INITIAL_DATA)__\s*=\s*")


def json_from_html(html):
    """Достает из страницы куски json, в которых может быть описан товар.
    Сначала идет разметка schema.org с товаром, потом все остальное."""
    products = []
    other = []
    decoder = json.JSONDecoder()

    for attrs, body in SCRIPT_RE.findall(html):
        attrs = attrs.lower()
        body = body.strip()
        if not body:
            continue

        if "ld+json" in attrs or "application/json" in attrs:
            try:
                data = json.loads(body)
            except ValueError:
                continue
            items = data if isinstance(data, list) else [data]
            if isinstance(data, dict) and "@graph" in data:
                items = data["@graph"]
            for item in items:
                if is_product(item):
                    products.append(item)
                else:
                    other.append(item)
        else:
            # window.__INITIAL_STATE__ = {...};
            # где кончается объект, регуляркой не найти, raw_decode находит сам
            for m in STATE_RE.finditer(body):
                try:
                    data, _ = decoder.raw_decode(body, m.end())
                    other.append(data)
                except ValueError:
                    pass

    return products + other


def format_price(kop):
    """129990 -> '1 299,90 ₽'"""
    if kop is None:
        return "-"
    rub, k = divmod(kop, 100)
    text = f"{rub:,}".replace(",", " ")
    if k:
        text += f",{k:02d}"
    return text + " ₽"
