import requests

from config import HEADERS, TIMEOUT


class FetchError(Exception):
    pass


class NotFoundError(FetchError):
    pass


session = requests.Session()
session.headers.update(HEADERS)


def get_page(url, params=None):
    try:
        resp = session.get(url, params=params, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise FetchError(f"не удалось подключиться ({e.__class__.__name__})")

    if resp.status_code in (404, 410):
        raise NotFoundError("товар не найден (404)")
    if resp.status_code != 200:
        raise FetchError(f"сайт ответил кодом {resp.status_code}")
    return resp


def get_html(url):
    return get_page(url).text


def get_json(url, params=None):
    resp = get_page(url, params)
    try:
        return resp.json()
    except ValueError:
        # обычно это значит, что вместо данных показали капчу
        raise FetchError("сайт вернул не json")
