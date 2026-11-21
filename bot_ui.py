from telebot import types

from parsers import PARSERS
from price_finder import format_price

MY_PRODUCTS = "Мои товары"
ADD_PRODUCT = "Добавить товар"
CHECK_PRICES = "Проверить цены"
HELP_BUTTON = "Помощь"
CANCEL = "Отмена"
MENU_BUTTONS = (MY_PRODUCTS, ADD_PRODUCT, CHECK_PRICES, HELP_BUTTON, CANCEL)

STORE_NAMES = {parser.name: parser.title for parser in PARSERS}
STATUS_LABELS = {
    None: "Ещё не проверяли",
    "": "Ещё не проверяли",
    "ok": "Цена обновлена",
    "not_found": "Товар не найден в магазине",
    "no_price": "Цена временно недоступна",
    "error": "Не удалось обновить цену",
}


def main_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(MY_PRODUCTS, ADD_PRODUCT)
    keyboard.row(CHECK_PRICES, HELP_BUTTON)
    return keyboard


def cancel_keyboard():
    keyboard = main_keyboard()
    keyboard.row(CANCEL)
    return keyboard


def product_keyboard(product_id):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(types.InlineKeyboardButton("🔄 Проверить цену", callback_data=f"check:{product_id}"))
    keyboard.row(
        types.InlineKeyboardButton("📈 График", callback_data=f"history:{product_id}"),
        types.InlineKeyboardButton("💰 Изменить порог", callback_data=f"threshold:{product_id}"),
    )
    keyboard.row(types.InlineKeyboardButton("Удалить", callback_data=f"remove:{product_id}"))
    return keyboard


def product_card(product, price):
    title = product["title"] or "Товар"
    store = STORE_NAMES.get(product["store"], "Другой магазин")
    status = STATUS_LABELS.get(product["last_status"], "Не удалось обновить цену")
    price_label = "Текущая цена" if product["last_status"] == "ok" else "Последняя известная цена"
    threshold = format_price(product["threshold_kop"]) if product["threshold_kop"] else "не задан"
    checked_at = product["last_checked_at"] or "ещё не проводилась"
    price_text = format_price(price) if price is not None else "ещё не получена"
    return (
        f"📦 #{product['id']} {title[:700]}\n"
        f"Магазин — {store}\n"
        f"{price_label} — {price_text}\n"
        f"Ваш порог — {threshold}\n"
        f"Статус — {status}\n"
        f"Последняя проверка — {checked_at}\n"
        f"{product['url']}"
    )
