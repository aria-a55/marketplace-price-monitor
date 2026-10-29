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
