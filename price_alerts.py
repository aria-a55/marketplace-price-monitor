from price_finder import format_price

SALE_DROP_PERCENT = 15


def is_sale(before, after):
    return before is not None and before > 0 and after * 100 <= before * (100 - SALE_DROP_PERCENT)


def price_alert(product, before, after):
    """Объединяет уведомления о резком снижении и переходе через порог."""
    if after is None:
        return None

    lines = []
    if is_sale(before, after):
        percent = (before - after) * 100 / before
        lines.append(f"Возможная распродажа! Цена упала на {percent:.1f}%.")
        lines.append(f"Было {format_price(before)}, стало {format_price(after)}.")

    threshold = product["threshold_kop"]
    if threshold and after <= threshold and (before is None or before > threshold):
        lines.append(f"Цена {format_price(after)} ниже вашего порога {format_price(threshold)}.")

    if not lines:
        return None
    lines.extend([product["title"] or f"Товар #{product['id']}", product["url"]])
    return "\n".join(lines)
