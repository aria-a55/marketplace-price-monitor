"""Telegram-бот. Запуск: python bot.py."""

import queue
import re
import sys
import threading
import time
import traceback

import telebot
from telebot import apihelper

import browser
import db
from agent import PriceAgent
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
/history <номер> - история цен и график товара
/threshold <номер> <цена> - изменить порог (0 - убрать)
/remove <номер> - перестать следить за товаром"""

URL_RE = re.compile(r"https?://\S+|\b[\w.-]+\.(?:ru|com)/\S+")
NUMBER_RE = re.compile(r"\d[\d\s]*(?:[.,]\d{1,2})?")

if not TELEGRAM_TOKEN:
    print("Нет токена бота. Получите его у @BotFather и положите в файл bot_token.txt рядом с main.py")
    sys.exit(1)

if TELEGRAM_PROXY:
    apihelper.proxy = {"https": TELEGRAM_PROXY}

# Playwright работает в одном потоке worker.
bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
jobs = queue.Queue()


def send(chat_id, text):
    try:
        bot.send_message(chat_id, text[:4000], disable_web_page_preview=True)
    except Exception as e:
        print("не удалось отправить сообщение:", e)


def parse_rub(text):
    """'1 499,90' -> 149990 копеек"""
    return round(float(text.replace(" ", "").replace(",", ".")) * 100)


def own_product(conn, message):
    """Товар по номеру из команды, если он принадлежит этому пользователю."""
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].lstrip("#").isdigit():
        send(message.chat.id, "Укажите номер товара, например: " + parts[0] + " 1")
        return None
    product = db.get_product(conn, int(parts[1].lstrip("#")))
    if not product or product["chat_id"] != message.chat.id or not product["is_active"]:
        send(message.chat.id, "Нет такого товара. Номера товаров есть в /list")
        return None
    return product


# ---- команды ----

@bot.message_handler(commands=["start", "help"])
def cmd_help(message):
    send(message.chat.id, HELP)


@bot.message_handler(commands=["list"])
def cmd_list(message):
    conn = db.connect()
    lines = []
    for p in db.get_products(conn, message.chat.id):
        price = format_price(db.get_last_price(conn, p["id"]))
        lines.append(f"#{p['id']} {p['title'] or p['url']}\n"
                     f"цена: {price}, порог: {format_price(p['threshold_kop'])}, "
                     f"статус: {p['last_status'] or 'еще не проверяли'}")
    conn.close()
    send(message.chat.id, "\n\n".join(lines) or "Вы пока не следите ни за одним товаром. Пришлите ссылку.")


@bot.message_handler(commands=["history"])
def cmd_history(message):
    conn = db.connect()
    try:
        product = own_product(conn, message)
        if product is None:
            return
        rows = db.get_history(conn, product["id"])
    finally:
        conn.close()

    lines = [f"{row['checked_at']}  {format_price(row['price_kop'])}" for row in rows[-15:]]
    send(message.chat.id, f"#{product['id']} {product['title'] or product['url']}\n\n"
                          + ("\n".join(lines) or "История пока пустая"))
    if rows:
        try:
            from charts import build_price_chart

            with build_price_chart(rows, product["threshold_kop"]) as chart:
                bot.send_photo(message.chat.id, chart, caption=f"История цен товара #{product['id']}")
        except ModuleNotFoundError as error:
            if error.name != "matplotlib":
                raise
            send(message.chat.id, "Для графиков установите зависимости: pip install -r requirements.txt")
        except Exception:
            traceback.print_exc()
            send(message.chat.id, "Не удалось отправить график цен.")


@bot.message_handler(commands=["threshold"])
def cmd_threshold(message):
    conn = db.connect()
    product = own_product(conn, message)
    if product:
        parts = message.text.split()
        try:
            value = parse_rub(parts[2]) if len(parts) > 2 else 0
        except ValueError:
            value = None
        if value is None or value < 0:
            send(message.chat.id, "Порог должен быть числом, например: /threshold 1 1500")
        else:
            db.set_threshold(conn, product["id"], value or None)
            send(message.chat.id, f"Порог для #{product['id']}: {format_price(value or None)}")
    conn.close()


@bot.message_handler(commands=["remove"])
def cmd_remove(message):
    conn = db.connect()
    product = own_product(conn, message)
    if product:
        db.remove_product(conn, product["id"])
        send(message.chat.id, f"Больше не слежу за #{product['id']}")
    conn.close()


@bot.message_handler(commands=["check"])
def cmd_check(message):
    jobs.put(("check", message.chat.id))
    send(message.chat.id, "Проверяю цены, это может занять несколько минут.")


@bot.message_handler(content_types=["text"])
def on_text(message):
    found = URL_RE.search(message.text)
    if not found:
        send(message.chat.id, "Пришлите ссылку на товар. Список команд - /help")
        return

    url = clean_url(found.group(0))
    threshold = None
    number = NUMBER_RE.search(message.text.replace(found.group(0), " "))
    if number:
        threshold = parse_rub(number.group(0).strip())

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

    send(chat_id, text)
    if saved:
        notify_price_change(conn, agent.product_id, before)


def notify_price_change(conn, product_id, before):
    product = db.get_product(conn, product_id)
    if not product["chat_id"]:
        return
    after = db.get_last_price(conn, product_id)
    text = price_alert(product, before, after)
    if text:
        send(product["chat_id"], text)


def check_products(conn, chat_id=None):
    """Проверяет товары и отправляет отчёт при ручном запросе."""
    report = []
    for product in db.get_products(conn, chat_id):
        before = db.get_last_price(conn, product["id"])
        status, info = check_product(conn, product)
        report.append(f"#{product['id']}  {info}")

        if status == "ok":
            notify_price_change(conn, product["id"], before)
    if chat_id is not None:
        send(chat_id, "\n".join(report) or "Вы пока не следите ни за одним товаром.")


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
                check_products(conn, job[1])
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
