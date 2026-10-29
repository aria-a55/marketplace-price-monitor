"""
Мониторинг цен на маркетплейсах.

    python main.py add <ссылка> --threshold 1500   добавить товар
    python main.py list                            список товаров
    python main.py check                           проверить цены
    python main.py history <id>                    история цен товара
    python main.py remove <id>                     перестать следить за товаром
"""

import argparse
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import db
from http_client import FetchError, NotFoundError
from parsers import UnknownStore, find_parser, parser_by_name
from parsers.base import PriceNotFound
from price_finder import format_price


def clean_url(url):
    # убираем #якорь и рекламные метки utm_..., чтобы один товар не добавился дважды
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    parts = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.startswith("utm_")]
    return urlunparse(parts._replace(netloc=parts.netloc.lower(),
                                     query=urlencode(query), fragment=""))


def rub_to_kop(text):
    try:
        value = float(text.replace(" ", "").replace(",", "."))
    except ValueError:
        raise argparse.ArgumentTypeError("порог должен быть числом, например 1500 или 1499,90")
    if value <= 0:
        raise argparse.ArgumentTypeError("порог должен быть больше нуля")
    return round(value * 100)


def add(conn, url, threshold):
    url = clean_url(url)
    try:
        parser = find_parser(url)
    except UnknownStore as e:
        print("Ошибка:", e)
        return
    product_id = db.add_product(conn, url, parser.name, parser.get_product_id(url), threshold)
    print(f"Товар #{product_id} добавлен ({parser.title}), порог: {format_price(threshold)}")


def show_list(conn):
    products = db.get_products(conn)
    if not products:
        print("Товаров пока нет. Добавить: python main.py add <ссылка> --threshold 1500")
        return
    for p in products:
        price = format_price(db.get_last_price(conn, p["id"]))
        status = p["last_status"] or "еще не проверяли"
        print(f"#{p['id']}  {p['store']:<14} цена: {price:<12} "
              f"порог: {format_price(p['threshold_kop']):<10} статус: {status}")
        print("    ", p["title"] or p["url"])


def show_history(conn, product_id):
    rows = db.get_history(conn, product_id)
    if not rows:
        print("История пустая")
    for row in rows:
        print(row["checked_at"], " ", format_price(row["price_kop"]))


def check_product(conn, product):
    pid = product["id"]
    try:
        parser = parser_by_name(product["store"])
        price, title = parser.get_price(product["url"])
    except NotFoundError as e:
        return failed(conn, pid, "not_found", e)
    except PriceNotFound as e:
        return failed(conn, pid, "no_price", e)
    except (FetchError, UnknownStore) as e:
        return failed(conn, pid, "error", e)

    db.save_price(conn, pid, price)
    db.set_status(conn, pid, "ok", title)
    print(f"#{pid}  {format_price(price)}  {title or ''}")
    return "ok"


def failed(conn, pid, status, error):
    # ошибка одного товара не должна останавливать проверку остальных
    print(f"#{pid}  ошибка: {error}")
    db.set_status(conn, pid, status)
    return status


def check_all(conn):
    products = db.get_products(conn)
    ok = 0
    for product in products:
        if check_product(conn, product) == "ok":
            ok += 1
    print(f"Проверено {len(products)}, успешно {ok}")


def main():
    parser = argparse.ArgumentParser(description="Мониторинг цен на маркетплейсах")
    commands = parser.add_subparsers(dest="command", required=True)

    cmd_add = commands.add_parser("add", help="добавить товар по ссылке")
    cmd_add.add_argument("url")
    cmd_add.add_argument("--threshold", type=rub_to_kop, help="порог цены в рублях")

    commands.add_parser("list", help="список товаров")
    commands.add_parser("check", help="проверить цены")

    cmd_history = commands.add_parser("history", help="история цен товара")
    cmd_history.add_argument("id", type=int)

    cmd_remove = commands.add_parser("remove", help="перестать следить за товаром")
    cmd_remove.add_argument("id", type=int)

    args = parser.parse_args()
    conn = db.connect()

    if args.command == "add":
        add(conn, args.url, args.threshold)
    elif args.command == "list":
        show_list(conn)
    elif args.command == "check":
        check_all(conn)
    elif args.command == "history":
        show_history(conn, args.id)
    elif args.command == "remove":
        db.remove_product(conn, args.id)
        print(f"Товар #{args.id} больше не проверяется")

    conn.close()


if __name__ == "__main__":
    main()
