"""
ИИ-агент мониторинга цен.

Страница открывается программой до обращения к Qwen:
1. определяем магазин;
2. открываем ссылку через рекомендуемый для магазина способ;
3. пробуем извлечь цену обычным парсером;
4. если парсер не справился, передаем текст страницы Qwen;
5. проверяем цену и только после этого сохраняем ее.
"""

import json
import re

import db
from ai import AIUnavailable, ask_ai, chat, page_text, price_on_page
from browser import get_html_browser
from config import AGENT_MAX_STEPS, ALLOW_BROWSER
from http_client import FetchError, NotFoundError, get_html
from parsers import UnknownStore, find_parser
from parsers.base import PriceNotFound
from price_finder import format_price, to_kopecks

TEXT_PART = 3000

SYSTEM_PROMPT = """Ты ИИ-агент для анализа уже открытой страницы товара.
Страница была открыта программой. Не проси пользователя открыть ссылку вручную.
Используй read_page_text, чтобы прочитать текст страницы, если он нужен.
Найди цену именно основного товара: не старую цену, не цену похожих товаров,
не рассрочку и не доставку. Затем вызови validate_price.
Если проверка успешна, вызови save_price. Никогда не выдумывай цену.
Если цены нет или страница показывает блокировку, сообщи об этом."""


def tool(name, description, params=None):
    props = {}
    for pname, (ptype, pdesc) in (params or {}).items():
        props[pname] = {"type": ptype, "description": pdesc}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": list(props),
            },
        },
    }


# Инструменты, которые нужны Qwen после загрузки страницы.
TOOLS = [
    tool("read_page_text", "Прочитать часть текста уже открытой страницы",
         {"part": ("integer", "номер части, начиная с 1")}),
    tool("validate_price", "Проверить найденную цену",
         {"price": ("number", "цена в рублях")}),
    tool("save_price", "Сохранить проверенную цену",
         {"price": ("number", "цена в рублях"),
          "title": ("string", "название товара")}),
]


class PriceAgent:
    def __init__(self, conn, url, threshold_kop=None, chat_id=0):
        self.conn = conn
        self.url = url
        self.threshold = threshold_kop
        self.chat_id = chat_id        # пользователь телеграма (0 - консоль)
        self.steps = []               # что делал агент - показываем пользователю в боте
        self.ai_failed = False        # True, если модель недоступна
        self.parser = None
        self.html = None
        self.text = ""
        self.code_price = None
        self.validated = None
        self.saved = None
        self.product_id = db.find_product(conn, url, chat_id)

    def detect_store(self):
        self.steps.append("detect_store")
        try:
            self.parser = find_parser(self.url)
        except UnknownStore as exc:
            return {"supported": False, "error": str(exc)}
        return {
            "supported": True,
            "store": self.parser.title,
            "recommended_method": "browser" if self.parser.use_browser else "http",
            "browser_allowed": ALLOW_BROWSER,
        }

    def fetch_page(self, method="http"):
        self.steps.append(f"fetch_page({method})")
        if not self.parser:
            return {"ok": False, "error": "сначала нужно определить магазин"}
        if method == "browser" and not ALLOW_BROWSER:
            return {"ok": False, "error": "браузер запрещен в config.py"}
        try:
            self.html = get_html_browser(self.url) if method == "browser" else get_html(self.url)
        except NotFoundError as exc:
            return {"ok": False, "error": str(exc)}
        except FetchError as exc:
            return {"ok": False, "error": str(exc)}

        self.text = page_text(self.html)
        title_match = re.search(r"<title[^>]*>(.*?)</title>", self.html, re.S | re.I)
        title = title_match.group(1).strip()[:150] if title_match else None
        return {
            "ok": True,
            "method": method,
            "text_length": len(self.text),
            "page_title": title,
        }

    def extract_price(self):
        self.steps.append("extract_price")
        if self.html is None:
            return {"found": False, "error": "страница еще не загружена"}
        try:
            price, title = self.parser.find_in_page(self.html)
        except PriceNotFound as exc:
            return {"found": False, "error": str(exc)}
        self.code_price = price
        return {"found": True, "price": price / 100, "title": title}

    def read_page_text(self, part=1):
        self.steps.append("read_page_text")
        if not self.text:
            return {"error": "текст страницы пуст"}
        total = (len(self.text) + TEXT_PART - 1) // TEXT_PART
        part = min(max(int(part or 1), 1), total)
        start = (part - 1) * TEXT_PART
        return {
            "part": part,
            "parts_total": total,
            "text": self.text[start:start + TEXT_PART],
        }

    def validate_price(self, price):
        self.steps.append("validate_price")
        kop = to_kopecks(price)
        if not kop:
            return {"valid": False, "reason": "это не похоже на цену"}
        if not 100 <= kop <= 1_000_000_000:
            return {"valid": False, "reason": "цена вне разумных пределов (1 ₽ — 10 млн ₽)"}
        if kop != self.code_price and not price_on_page(kop, self.text):
            return {"valid": False, "reason": "такой цены нет в тексте страницы"}
        if self.code_price and kop != self.code_price:
            return {
                "valid": False,
                "reason": f"не совпадает с ценой парсера ({format_price(self.code_price)})",
            }
        if self.product_id:
            last = db.get_last_price(self.conn, self.product_id)
            if last and not last * 0.3 <= kop <= last * 3:
                return {
                    "valid": False,
                    "reason": f"сильное отличие от прошлой цены ({format_price(last)}); нужна проверка",
                }
        self.validated = kop
        return {"valid": True, "price_text": format_price(kop)}

    def save_price(self, price, title=None):
        self.steps.append("save_price")
        kop = to_kopecks(price)
        if kop is None or kop != self.validated:
            return {"saved": False, "error": "сначала цена должна пройти validate_price"}
        if self.product_id is None:
            self.product_id = db.add_product(
                self.conn, self.url, self.parser.name,
                self.parser.get_product_id(self.url), self.threshold, self.chat_id,
            )
        db.save_price(self.conn, self.product_id, kop)
        db.set_status(
            self.conn, self.product_id, "ok",
            title if isinstance(title, str) else None,
        )
        self.saved = kop
        result = {
            "saved": True,
            "product_id": self.product_id,
            "price_text": format_price(kop),
        }
        if self.threshold and kop <= self.threshold:
            result["below_threshold"] = True
        return result

    def call_tool(self, name, args):
        tools = {
            "read_page_text": lambda: self.read_page_text(args.get("part", 1)),
            "validate_price": lambda: self.validate_price(args.get("price")),
            "save_price": lambda: self.save_price(args.get("price"), args.get("title")),
        }
        if name not in tools:
            return {"error": f"неизвестный инструмент: {name}"}
        try:
            return tools[name]()
        except (TypeError, ValueError) as exc:
            return {"error": f"неправильные параметры: {exc}"}

    def _open_product_page(self):
        """Открывает URL сам, без ожидания команды от Qwen."""
        info = self.detect_store()
        if not info["supported"]:
            return info

        preferred = info["recommended_method"]
        if preferred == "browser":
            if not ALLOW_BROWSER:
                return {"ok": False, "error": "для этого магазина нужен браузер, но ALLOW_BROWSER=False"}
            result = self.fetch_page("browser")
            return result

        # Для магазинов с обычной загрузкой сначала используем HTTP.
        result = self.fetch_page("http")
        if result["ok"]:
            return result

        # Если HTTP не сработал, пробуем браузер, если он разрешен.
        if ALLOW_BROWSER:
            print("  [агент] HTTP не загрузил страницу, пробую открыть ее в браузере...")
            return self.fetch_page("browser")
        return result

    def _save_known_price(self, price_kop, title=None):
        validation = self.validate_price(price_kop / 100)
        if not validation["valid"]:
            return validation
        return self.save_price(price_kop / 100, title)

    def _ask_qwen(self):
        """Дает Qwen возможность найти цену, если обычный парсер не справился."""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Магазин: {self.parser.title}\n"
                    f"Ссылка: {self.url}\n"
                    f"Текст страницы (первые 6000 символов):\n{self.text[:6000]}"
                ),
            },
        ]

        for _ in range(AGENT_MAX_STEPS):
            reply = chat(messages, tools=TOOLS)
            messages.append(reply)
            calls = reply.get("tool_calls") or []
            if not calls:
                if self.saved:
                    # Qwen уже сохранил цену через save_price и просто пишет итог
                    return reply.get("content") or f"Qwen нашел цену: {format_price(self.saved)}."
                # Если Qwen не вызвал инструменты, пробуем обычный JSON-режим как резерв.
                self.steps.append("ask_ai")
                found = ask_ai(self.html)
                if found:
                    price_kop, title = found
                    result = self._save_known_price(price_kop, title)
                    if result.get("saved"):
                        return f"Qwen нашел цену: {format_price(price_kop)}."
                    return f"Цена от ИИ не прошла проверку: {result.get('reason', result.get('error'))}."
                return reply.get("content") or "Qwen не смог определить цену."
            for call in calls:
                function = call.get("function") or {}
                name = function.get("name")
                args = function.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {}
                result = self.call_tool(name, args)
                print(
                    f"  [агент] {name} -> "
                    f"{json.dumps({k: v for k, v in result.items() if k != 'text'}, ensure_ascii=False)}"
                )
                messages.append({
                    "role": "tool",
                    "tool_name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                })
        return "Агент достиг лимита шагов и остановился."

    def run(self):
        try:
            print(f"  [агент] Открываю ссылку: {self.url}")
            opened = self._open_product_page()
            if not opened.get("ok"):
                return self.finish(opened.get("error") or "Не удалось открыть страницу.")

            print(
                f"  [агент] Страница открыта "
                f"({opened.get('method')}), заголовок: {opened.get('page_title') or 'не указан'}"
            )

            extracted = self.extract_price()
            if extracted.get("found"):
                price_kop = to_kopecks(extracted["price"])
                result = self._save_known_price(price_kop, extracted.get("title"))
                if result.get("saved"):
                    return self.finish(
                        f"Парсер нашел цену {format_price(price_kop)}. "
                        "Qwen не понадобился: цена уже определена и проверена кодом."
                    )
                # Если проверка не прошла (например, сильное изменение), не сохраняем.
                return self.finish(
                    f"Цена {format_price(price_kop)} найдена, но не сохранена: "
                    f"{result.get('reason', result.get('error'))}"
                )

            print("  [агент] Парсер не нашел цену, передаю текст страницы Qwen...")
            answer = self._ask_qwen()
            return self.finish(answer)

        except AIUnavailable as exc:
            self.ai_failed = True
            return self.finish(str(exc))
        finally:
            # Если использовался управляемый браузер, корректно отключаемся.
            from browser import close
            close()

    def finish(self, text):
        text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
        if self.saved:
            fact = f"Итог: цена {format_price(self.saved)} сохранена (товар #{self.product_id})."
        else:
            fact = "Итог: цена не сохранена."
            if self.product_id:
                db.set_status(self.conn, self.product_id, "error")
        return f"{text}\n{fact}" if text else fact


def run_agent(conn, url, threshold_kop=None):
    return PriceAgent(conn, url, threshold_kop).run()
