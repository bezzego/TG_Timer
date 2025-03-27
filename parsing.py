import dateparser
import datetime
from pytimeparse import parse as parse_seconds


def parse_time_input(user_input: str):
    """
    Сначала пытается распарсить dateparser'ом (естественный язык),
    Если не получилось (None или время в прошлом),
    то пробуем pytimeparse (простой формат 30s, 1m, 2h).

    Возвращает int (количество секунд) или None, если парс не удался.
    """
    # 1) Пытаемся через dateparser
    import dateparser

    dt = dateparser.parse(
        user_input,
        languages=['ru'],  # <--- указываем язык (или ['ru', 'en'] если хотим мультиязычность)
        settings={
            'RETURN_AS_TIMEZONE_AWARE': False,
            'PREFER_DATES_FROM': 'future'
        }
    )
    if dt:
        now = datetime.datetime.now()
        # Если dt > now => считаем разницу
        if dt > now:
            delta = dt - now
            return int(delta.total_seconds())
    # 2) Пытаемся через pytimeparse (формат типа '30s', '1m', '2h')
    secs = parse_seconds(user_input)
    if secs is not None:
        return secs

    return None