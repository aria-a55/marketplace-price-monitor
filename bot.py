"""Telegram-бот. Запуск: python bot.py."""

import queue
import re
import sys
import threading
import time
import traceback
from contextlib import closing
from decimal import Decimal, InvalidOperation

import telebot
from telebot import apihelper

import browser
import db
from agent import PriceAgent
from bot_ui import (
    ADD_PRODUCT, CANCEL, CHECK_PRICES, HELP_BUTTON, MENU_BUTTONS, MY_PRODUCTS,
    cancel_keyboard, main_keyboard, product_card, product_keyboard,
)
from config import CHECK_INTERVAL_MINUTES, TELEGRAM_PROXY, TELEGRAM_TOKEN
from main import check_product, clean_url
from parsers import UnknownStore, find_parser
from price_finder import format_price
from price_alerts import price_alert

HELP = """Я слежу за ценами в интернет-магазинах: Читай-город, Яндекс Маркет, Kari.

Пришлите ссылку на товар, можно сразу с порогом цены:
https://www.chitai-gorod.ru/product/... 500
Когда цена опустится ниже порога, я напишу.
Также сообщу о возможной распродаже — падении цены на 15% и более с прошлой проверки.

Команды:
/list - мои товары
/check - проверить цены сейчас
/check <номер> - проверить цену одного товара
/history <номер> - история цен и график товара
/threshold <номер> <цена> - изменить порог (0 - убрать)
/remove <номер> - перестать следить за товаром
/cancel - отменить ввод порога

Можно пользоваться кнопками меню и кнопками под товарами."""

URL_RE = re.compile(r"https?://\S+|\b[\w.-]+\.(?:ru|com)/\S+")
NUMBER_RE = re.compile(r"\d[\d\s]*(?:[.,]\d{1,2})?")
ACTION_RE = re.compile(r"(check|history|threshold|remove):([1-9]\d*)")

if not TELEGRAM_TOKEN:
    print("Нет токена бота. Получите его у @BotFather и положите в файл bot_token.txt рядом с main.py")
    sys.exit(1)

if TELEGRAM_PROXY:
    apihelper.proxy = {"https": TELEGRAM_PROXY}

# Playwright работает в одном потоке worker.
bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
jobs = queue.Queue()
pending_thresholds = {}


def send(chat_id, text, reply_markup=None):
    try:
        bot.send_message(chat_id, text[:4000], disable_web_page_preview=True,
                         reply_markup=reply_markup if reply_markup is not None else main_keyboard())
    except Exception as e:
        print("не удалось отправить сообщение:", e)


def parse_rub(text):
    """'1 499,90' -> 149990 копеек"""
    try:
        value = Decimal(text.replace(" ", "").replace("\xa0", "").replace(",", "."))
        if not value.is_finite() or value < 0:
            raise ValueError
        kop = round(value * 100)
    except (InvalidOperation, OverflowError):
        raise ValueError("Некорректная цена") from None
    if kop > 9_223_372_036_854_775_807:
        raise ValueError("Слишком большая цена")
    return kop


def owned_product(conn, product_id, chat_id):
    product = db.get_product(conn, product_id)
    if product and product["chat_id"] == chat_id and product["is_active"]:
        return product
    return None


def send_product(conn, product, intro=None):
    price = db.get_last_price(conn, product["id"])
    text = product_card(product, price)
    if intro:
        text = intro + "\n\n" + text
    send(product["chat_id"], text, product_keyboard(product["id"]))


def own_product(conn, message):
    """Товар по номеру из команды, если он принадлежит этому пользователю."""
    pending_thresholds.pop((message.chat.id, message.from_user.id), None)
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].lstrip("#").isdigit():
        send(message.chat.id, "Укажите номер товара, например: " + parts[0] + " 1")
        return None
    product = owned_product(conn, int(parts[1].lstrip("#")), message.chat.id)
    if product is None:
        send(message.chat.id, "Товар недоступен. Откройте «Мои товары».")
    return product


# ---- команды ----

@bot.message_handler(commands=["start", "help"])
def cmd_help(message):
    pending_thresholds.pop((message.chat.id, message.from_user.id), None)
    send(message.chat.id, HELP)


@bot.message_handler(commands=["list"])
def cmd_list(message):
    pending_thresholds.pop((message.chat.id, message.from_user.id), None)
    with closing(db.connect()) as conn:
        products = db.get_products(conn, message.chat.id)
        if not products:
            send(message.chat.id, "Вы пока не следите ни за одним товаром. Нажмите «Добавить товар».")
        for product in products:
            send_product(conn, product)


@bot.message_handler(commands=["history"])
def cmd_history(message):
    with closing(db.connect()) as conn:
        product = own_product(conn, message)
        if product is not None:
            send_history(conn, product)


def send_history(conn, product):
    rows = db.get_history(conn, product["id"])
    lines = [f"{row['checked_at']}  {format_price(row['price_kop'])}" for row in rows[-15:]]
    send(product["chat_id"], f"#{product['id']} {product['title'] or product['url']}\n\n"
                            + ("\n".join(lines) or "История пока пустая"),
         product_keyboard(product["id"]))
    if rows:
        try:
            from charts import build_price_chart

            with build_price_chart(rows, product["threshold_kop"]) as chart:
                bot.send_photo(product["chat_id"], chart, caption=f"История цен товара #{product['id']}")
        except ModuleNotFoundError as error:
            if error.name != "matplotlib":
                raise
            print("Для графиков установите зависимости: pip install -r requirements.txt")
            send(product["chat_id"], "График временно недоступен. История цен показана выше.")
        except Exception:
            traceback.print_exc()
            send(product["chat_id"], "Не удалось отправить график цен. Попробуйте позже.")


@bot.message_handler(commands=["threshold"])
def cmd_threshold(message):
    with closing(db.connect()) as conn:
        product = own_product(conn, message)
        if product is not None:
            parts = message.text.split(maxsplit=2)
            if not update_threshold(conn, product, parts[2] if len(parts) > 2 else "0"):
                pending_thresholds[(message.chat.id, message.from_user.id)] = product["id"]


def update_threshold(conn, product, text):
    try:
        value = parse_rub(text)
    except ValueError:
        send(product["chat_id"], "Введите цену в рублях, например 1499,90. Чтобы убрать порог, введите 0.",
             cancel_keyboard())
        return False
    db.set_threshold(conn, product["id"], value or None)
    send(product["chat_id"], "Порог обновлён." if value else "Порог отключён.")
    send_product(conn, db.get_product(conn, product["id"]))
    return True


@bot.message_handler(commands=["remove"])
def cmd_remove(message):
    with closing(db.connect()) as conn:
        product = own_product(conn, message)
        if product is not None:
            db.remove_product(conn, product["id"])
            send(message.chat.id, f"Отслеживание товара #{product['id']} отключено.")


@bot.message_handler(commands=["check"])
def cmd_check(message):
    pending_thresholds.pop((message.chat.id, message.from_user.id), None)
    parts = message.text.split()
    if parts[0].startswith("/") and len(parts) > 1:
        with closing(db.connect()) as conn:
            product = own_product(conn, message)
            if product is not None:
                enqueue_check(message.chat.id, product["id"])
    else:
        enqueue_check(message.chat.id)


def enqueue_check(chat_id, product_id=None):
    jobs.put(("check", chat_id, product_id))
    text = f"Проверяю цену товара #{product_id}" if product_id is not None else "Проверяю цены"
    send(chat_id, text + ", это может занять несколько минут.")


@bot.message_handler(commands=["cancel"])
def cmd_cancel(message):
    pending_thresholds.pop((message.chat.id, message.from_user.id), None)
    send(message.chat.id, "Действие отменено.")


@bot.message_handler(func=lambda message: message.text in MENU_BUTTONS)
def on_menu(message):
    pending_thresholds.pop((message.chat.id, message.from_user.id), None)
    if message.text == MY_PRODUCTS:
        cmd_list(message)
    elif message.text == CHECK_PRICES:
        cmd_check(message)
    elif message.text == HELP_BUTTON:
        cmd_help(message)
    elif message.text == CANCEL:
        cmd_cancel(message)
    elif message.text == ADD_PRODUCT:
        send(message.chat.id, "Пришлите ссылку на товар из Читай-города, Яндекс Маркета или Kari.\n"
                             "Можно сразу указать порог цены после ссылки, например 1500.")


@bot.callback_query_handler(func=lambda call: True)
def on_product_action(call):
    action_match = ACTION_RE.fullmatch(call.data or "")
    if not action_match or call.message is None:
        bot.answer_callback_query(call.id, "Эта кнопка недоступна.")
        return

    action, product_id = action_match.groups()
    chat_id = call.message.chat.id
    key = (chat_id, call.from_user.id)
    with closing(db.connect()) as conn:
        product = owned_product(conn, int(product_id), chat_id)
        if product is None:
            bot.answer_callback_query(call.id, "Товар недоступен. Откройте «Мои товары».", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        pending_thresholds.pop(key, None)
        if action == "check":
            enqueue_check(chat_id, product["id"])
        elif action == "history":
            send_history(conn, product)
        elif action == "threshold":
            pending_thresholds[key] = product["id"]
            send(chat_id, f"Введите новый порог для товара #{product['id']} в рублях.\n"
                          "Например, 1499,90. Чтобы убрать порог, введите 0.",
                 cancel_keyboard())
        elif action == "remove":
            db.remove_product(conn, product["id"])
            try:
                bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
            except telebot.apihelper.ApiTelegramException as error:
                print("Не удалось убрать кнопки удалённого товара:", error)
            send(chat_id, f"Отслеживание товара #{product['id']} отключено.")


@bot.message_handler(content_types=["text"])
def on_text(message):
    found = URL_RE.search(message.text)
    key = (message.chat.id, message.from_user.id)
    product_id = pending_thresholds.get(key)
    if product_id is not None and not found and not message.text.startswith("/"):
        with closing(db.connect()) as conn:
            product = owned_product(conn, product_id, message.chat.id)
            if product is None:
                pending_thresholds.pop(key, None)
                send(message.chat.id, "Товар недоступен. Откройте «Мои товары».")
            elif update_threshold(conn, product, message.text):
                pending_thresholds.pop(key, None)
        return

    pending_thresholds.pop(key, None)
    if not found:
        send(message.chat.id, "Выберите действие в меню или пришлите ссылку на товар.")
        return

    url = clean_url(found.group(0))
    threshold = None
    number = NUMBER_RE.search(message.text.replace(found.group(0), " "))
    if number:
        try:
            threshold = parse_rub(number.group(0).strip()) or None
        except ValueError:
            send(message.chat.id, "Не удалось прочитать порог цены. Пришлите ссылку и цену в рублях.")
            return

    try:
        find_parser(url)
    except UnknownStore as e:
        text = str(e)
        send(message.chat.id, text[0].upper() + text[1:])
        return

    waiting = jobs.qsize()
    send(message.chat.id, "Принято, узнаю цену. Это может занять пару минут"
                          + (f" (передо мной в очереди: {waiting})" if waiting else "") + ".")
    jobs.put(("agent", message.chat.id, url, threshold))


# ---- работа с сайтами (в отдельном потоке) ----

def run_agent_job(conn, chat_id, url, threshold):
    product_id = db.find_product(conn, url, chat_id)
    before = db.get_last_price(conn, product_id) if product_id else None
    if product_id and threshold:
        db.set_threshold(conn, product_id, threshold)

    agent = PriceAgent(conn, url, threshold, chat_id)
    text = agent.run()
    saved = agent.saved is not None
    if agent.ai_failed:
        parser = find_parser(url)
        product_id = db.add_product(conn, url, parser.name, parser.get_product_id(url), threshold, chat_id)
        status, info = check_product(conn, db.get_product(conn, product_id))
        saved = status == "ok"
        text = f"ИИ сейчас недоступен, проверил обычным способом.\n#{product_id}  {info}"
        agent.product_id = product_id

    if saved:
        send_product(conn, db.get_product(conn, agent.product_id), intro="Отслеживание включено.")
    else:
        print(text)
        send(chat_id, "Не удалось получить цену товара. Попробуйте позже.")
        if agent.product_id:
            send_product(conn, db.get_product(conn, agent.product_id))
    if saved:
        notify_price_change(conn, agent.product_id, before)


def notify_price_change(conn, product_id, before):
    product = db.get_product(conn, product_id)
    if not product["chat_id"] or not product["is_active"]:
        return
    after = db.get_last_price(conn, product_id)
    text = price_alert(product, before, after)
    if text:
        send(product["chat_id"], text)


def check_products(conn, chat_id=None, product_id=None):
    """Проверяет товары и отправляет отчёт при ручном запросе."""
    if product_id is None:
        products = db.get_products(conn, chat_id)
    else:
        product = owned_product(conn, product_id, chat_id)
        if product is None:
            send(chat_id, "Товар недоступен. Откройте «Мои товары».")
            return
        products = [product]
    for product in products:
        before = db.get_last_price(conn, product["id"])
        status, _ = check_product(conn, product)
        if chat_id is not None:
            send_product(conn, db.get_product(conn, product["id"]))

        if status == "ok":
            notify_price_change(conn, product["id"], before)
    if chat_id is not None and not products:
        send(chat_id, "Вы пока не следите ни за одним товаром. Нажмите «Добавить товар».")


def worker():
    conn = db.connect()
    next_check = time.monotonic() + CHECK_INTERVAL_MINUTES * 60
    while True:
        if time.monotonic() >= next_check:
            job = ("check_all",)
        else:
            try:
                job = jobs.get(timeout=max(0, next_check - time.monotonic()))
            except queue.Empty:
                job = ("check_all",)

        try:
            if job[0] == "agent":
                run_agent_job(conn, *job[1:])
            elif job[0] == "check":
                check_products(conn, *job[1:])
            elif job[0] == "check_all":
                print("Плановая проверка цен")
                check_products(conn)
        except Exception:
            # ошибка в одной задаче не должна останавливать бота
            traceback.print_exc()
            if job[0] != "check_all":
                send(job[1], "Что-то пошло не так, попробуйте еще раз позже.")
        finally:
            if job[0] == "check_all":
                next_check = time.monotonic() + CHECK_INTERVAL_MINUTES * 60
            browser.close()


def main():
    try:
        me = bot.get_me()
    except Exception as e:
        print("Не удалось подключиться к Telegram:", e)
        print("Если Telegram недоступен, укажите прокси TELEGRAM_PROXY в config.py")
        sys.exit(1)

    threading.Thread(target=worker, daemon=True).start()
    print(f"Бот @{me.username} запущен. Остановить - Ctrl+C")
    bot.infinity_polling(timeout=30, long_polling_timeout=30)


if __name__ == "__main__":
    main()
