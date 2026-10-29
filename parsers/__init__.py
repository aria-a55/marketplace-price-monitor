from parsers.chitai_gorod import ChitaiGorodParser
from parsers.kari import KariParser
from parsers.yandex_market import YandexMarketParser

# чтобы добавить магазин, пишем для него класс и дописываем сюда
PARSERS = [ChitaiGorodParser, YandexMarketParser, KariParser]


class UnknownStore(Exception):
    pass


def find_parser(url):
    for parser in PARSERS:
        if parser.can_handle(url):
            return parser()
    names = ", ".join(p.title for p in PARSERS)
    raise UnknownStore(f"этот магазин пока не поддерживается (есть: {names})")


def parser_by_name(name):
    for parser in PARSERS:
        if parser.name == name:
            return parser()
    raise UnknownStore(f"неизвестный магазин {name}")
