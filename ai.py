"""
ИИ-помощник: локальная модель Qwen через Ollama.

Если обычный код не нашел цену на странице, отдаем модели текст страницы
и просим найти цену основного товара. Модель работает на этом же компьютере,
поэтому не нужны ни интернет-сервисы, ни VPN, ни оплата.
"""

import html as html_lib
import json
import re

import requests

from config import AI_MODEL, AI_TEXT_LIMIT, OLLAMA_URL
from price_finder import to_kopecks

PROMPT = (
    "Тебе дают текст страницы товара из интернет-магазина. "
    "Найди текущую цену основного товара: не старую зачеркнутую цену, "
    "не цену похожих товаров, не платеж в рассрочку и не цену доставки. "
    'Ответь только JSON вида {"price": 1299.0, "title": "название товара"}. '
    'Если цены на странице нет, ответь {"price": null, "title": null}.'
)


class AIUnavailable(Exception):
    pass


def page_text(html):
    """Видимый текст страницы без скриптов, стилей и тегов."""
    html = re.sub(r"<(script|style|noscript|svg)\b[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", html))
    return re.sub(r"\s+", " ", text).strip()


def price_on_page(price_kop, text):
    # проверка от "выдумывания": такое число должно реально быть на странице.
    # убираем пробелы внутри чисел, чтобы "2 390" превратилось в "2390"
    digits = re.sub(r"(?<=\d)[\s\u00a0\u2009\u202f](?=\d)", "", text)
    return str(price_kop // 100) in digits


def chat(messages, tools=None, json_answer=False):
    """Отправляет переписку модели и возвращает ее ответ (словарь message)."""
    body = {
        "model": AI_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,                                  # у qwen3 выключаем "размышления" - так быстрее
        "options": {"temperature": 0, "num_ctx": 8192},  # без фантазий, длинный контекст
    }
    if tools:
        body["tools"] = tools
    if json_answer:
        body["format"] = "json"
    try:
        resp = requests.post(OLLAMA_URL, json=body, timeout=300)
        if resp.status_code == 400 and "think" in resp.text:
            # модель без режима размышлений (например qwen2.5) - повторяем без этого параметра
            del body["think"]
            resp = requests.post(OLLAMA_URL, json=body, timeout=300)
        resp.raise_for_status()
        return resp.json()["message"]
    except (requests.RequestException, ValueError, KeyError):
        raise AIUnavailable("ИИ недоступен: проверьте, что Ollama запущена и модель скачана "
                            f"(ollama pull {AI_MODEL})")


def ask_ai(html):
    """Возвращает (цена в копейках, название) или None, если модель цену не нашла."""
    text = page_text(html)[:AI_TEXT_LIMIT]
    if not text:
        return None

    reply = chat([{"role": "system", "content": PROMPT},
                  {"role": "user", "content": text}], json_answer=True)
    try:
        answer = json.loads(reply.get("content") or "")
    except ValueError:
        return None

    if not isinstance(answer, dict):
        return None
    price = to_kopecks(answer.get("price"))
    if not price or not price_on_page(price, text):
        return None
    title = answer.get("title")
    return price, title if isinstance(title, str) and title.strip() else None
