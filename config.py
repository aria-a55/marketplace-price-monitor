import os

# папка проекта (там, где лежит этот файл)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# файл базы данных создается рядом с main.py
DB_PATH = os.path.join(BASE_DIR, "prices.db")

# сколько секунд ждем ответа от сайта
TIMEOUT = 15

# без нормального User-Agent магазины часто сразу отвечают 403
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

# браузер - для сайтов, которые не отдают страницу обычному запросу
# если Chrome запущен с параметром --remote-debugging-port=9222, программа подключается к нему.
# такой браузер сайты не отличают от обычного, поэтому блокируют реже
CDP_URL = "http://localhost:9222"
# если подключиться не удалось, программа запускает свой браузер с такими настройками:
# здесь браузер хранит свои cookies, как обычный браузер на компьютере
PROFILE_DIR = os.path.join(BASE_DIR, "browser_profile")
# "chrome" - открываем Chrome, установленный на компьютере.
# если его нет, используется Chromium (ставится командой: playwright install chromium)
BROWSER_CHANNEL = "chrome"
# False - окно браузера видно, чтобы при проверке "вы не робот" пройти ее вручную
BROWSER_HEADLESS = False
# сколько секунд ждать, пока проверку пройдут
CHECK_WAIT_SECONDS = 120

# ИИ: локальная модель через Ollama (https://ollama.com), скачать: ollama pull qwen3:4b
OLLAMA_URL = "http://localhost:11434/api/chat"
AI_MODEL = "qwen3:4b"
AI_TEXT_LIMIT = 6000      # сколько символов текста страницы отдаем модели за раз
# в команде check ИИ помогает, только если обычный код не нашел цену на странице
USE_AI = True

# ИИ-агент (команда agent)
ALLOW_BROWSER = True      # можно ли агенту открывать браузер
AGENT_MAX_STEPS = 12      # сколько раз агент может вызвать инструменты, чтобы не зациклиться
