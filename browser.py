"""
Открытие страниц в настоящем браузере через Playwright.

Нужно для сайтов, которые не отдают страницу обычному запросу:
браузер загружает страницу целиком, вместе с javascript, как у обычного человека.
Если сайт покажет проверку "вы не робот", ее можно пройти вручную в окне браузера,
программа подождет.

Сначала пробуем подключиться к Chrome, который пользователь открыл сам
(с параметром --remote-debugging-port).
"""

import random
import time

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from config import BROWSER_CHANNEL, BROWSER_HEADLESS, CDP_URL, CHECK_WAIT_SECONDS, PROFILE_DIR
from http_client import FetchError, NotFoundError

# по этим словам понимаем, что вместо товара показали проверку
BLOCK_WORDS = [
    "доступ ограничен",
    "не робот",
    "подозрительн",
    "captcha",
    "капч",
    "checking your browser",
    "проверка браузера",
    "antibot",
    "инцидент"
]

CONNECTION_ERROR_WORDS = [
    "похоже, нет соединения",
    "нет подключения к интернету",
    "err_internet_disconnected",
    "err_proxy_connection_failed",
    "err_name_not_resolved",
    "err_connection_reset",
    "err_tunnel_connection_failed"
]


def _is_connection_error(page):
    try:
        text = (page.title() + " " + page.inner_text("body")[:3000]).lower()
        return any(word in text for word in CONNECTION_ERROR_WORDS)
    except PlaywrightError:
        return False

# браузер запускаем один раз на всю проверку, а не для каждого товара
_playwright = None
_context = None
_connected = False   # True - работаем в Chrome пользователя, закрывать его нельзя


def _start():
    global _playwright, _context, _connected
    _playwright = sync_playwright().start()

    # 1) Chrome, открытый пользователем
    try:
        chrome = _playwright.chromium.connect_over_cdp(CDP_URL, timeout=3000)
        _context = chrome.contexts[0] if chrome.contexts else chrome.new_context()
        _connected = True
        print("Подключились к открытому Chrome")
        return
    except PlaywrightError:
        pass

    # 2) свой браузер
    options = dict(headless=BROWSER_HEADLESS, locale="ru-RU",
                   viewport={"width": 1366, "height": 850})
    try:
        _context = _playwright.chromium.launch_persistent_context(
            PROFILE_DIR, channel=BROWSER_CHANNEL, **options)
        return
    except PlaywrightError:
        pass  # chrome не установлен - попробуем chromium от playwright
    try:
        _context = _playwright.chromium.launch_persistent_context(PROFILE_DIR, **options)
    except PlaywrightError:
        close()
        raise FetchError("не удалось запустить браузер. Установите его командой: "
                         "playwright install chromium")


def close():
    global _playwright, _context, _connected
    try:
        if _context and not _connected:
            _context.close()
        if _playwright:
            _playwright.stop()   # от Chrome пользователя просто отключаемся, он остается открытым
    except PlaywrightError:
        pass  # браузер уже закрыт
    _playwright = None
    _context = None
    _connected = False


def _pause(a, b):
    time.sleep(random.uniform(a, b))


def _is_blocked(page, status):
    try:
        text = page.inner_text("body")
        title = page.title()
    except PlaywrightError:
        return True  # страница как раз перезагружается, подождем еще
    start = (title + " " + text[:3000]).lower()
    if any(word in start for word in BLOCK_WORDS):
        return True
    # сайт ответил 403/429 и на странице почти ничего нет - тоже заглушка
    return status in (403, 429) and len(text) < 2000


def _open(page, url):
    """Открывает страницу. Возвращает код ответа сайта (0, если не известен)."""
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        return response.status if response else 0
    except PlaywrightError as e:
        # сайты с защитой часто сразу перенаправляют на другую страницу,
        # playwright считает это ошибкой. просто ждем, пока новая страница загрузится
        if "interrupted by another navigation" not in str(e) and "ERR_ABORTED" not in str(e):
            raise
        page.wait_for_load_state("domcontentloaded", timeout=60000)
        return 0


def _content(page):
    # если страница в этот момент перезагружается, ждем и пробуем еще раз
    for _ in range(3):
        try:
            return page.content()
        except PlaywrightError as e:
            if "navigating" not in str(e):
                raise
            page.wait_for_load_state("domcontentloaded", timeout=30000)
    return page.content()


def _alive():
    try:
        _context.cookies()
        return True
    except PlaywrightError:
        return False


def get_html_browser(url):
    if _context is None:
        _start()

    page = None
    try:
        if _connected:
            # в Chrome пользователя открываем свою вкладку, а его вкладки не трогаем
            page = _context.new_page()
        else:
            # в своем браузере работаем в одной вкладке и не закрываем ее:
            # если закрыть последнюю вкладку, Chrome закрывает и окно
            page = _context.pages[0] if _context.pages else _context.new_page()
        status = _open(page, url)
        if status in (404, 410):
            raise NotFoundError("товар не найден (404)")

        _pause(2, 4)  # даем странице догрузиться

        if _is_connection_error(page):
            raise FetchError(
                "Браузер не смог подключиться к сайту. "
                "Проверьте интернет и доступность магазина."
            )

        if _is_blocked(page, status):
            print("Сайт показал проверку. Если в окне браузера есть кнопка или капча, "
                  f"пройдите ее или нажмите 'Обновить страницу'. Жду до {CHECK_WAIT_SECONDS} секунд...")
            deadline = time.time() + CHECK_WAIT_SECONDS
            while _is_blocked(page, status):
                if time.time() > deadline:
                    raise FetchError("сайт показал проверку, и она не пройдена")
                time.sleep(2)
            _pause(2, 3)

        # немного прокручиваем страницу, как обычный человек
        for _ in range(random.randint(2, 4)):
            page.mouse.wheel(0, random.randint(300, 700))
            _pause(0.5, 1.5)

        return _content(page)
    except PlaywrightError as e:
        detail = str(e).strip().splitlines()[0][:200] if str(e).strip() else e.__class__.__name__
        if not _alive():
            # браузер закрыли или он упал - для следующего товара запустим заново
            close()
            raise FetchError(f"браузер закрылся ({detail})")
        raise FetchError(f"ошибка в браузере: {detail}")
    finally:
        if page and _connected:
            try:
                page.close()
            except PlaywrightError:
                pass
