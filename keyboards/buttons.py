import logging

from config_data.config import Config

logger_buttons = logging.getLogger(__name__)

ADMIN_PANEL_BUTT: dict[str, str] = {
    'make_cert': 'Сделать сертификат',
    'add_admin': 'Добавить админа',
    'exit': 'Выход'}

BUTT_CANCEL: dict[str, str] = {'cancel': '❌ОТМЕНА'}
BUTT_BACK: dict[str, str] = {'back': '🔙 Назад'}
BUTT_DONE: dict[str, str] = {'done': 'Подтвердить✅'}

BUTT_NEWSLETTER: dict[str, str] = {}
BUTT_START: dict[str, str] = {
    'get_cert': 'Получить сертификат',
    'get_promo': 'Получить промокод со скидкой'}

BUTT_GENDER: dict[str, str] = {'male': 'Мужской ♂', 'female': 'Женский ♀'}


BUTT_COURSES: dict[str, str] = {}
BUTT_COURSES_PRAGMATIC: dict[str, str] = {}

def get_courses_buttons(config: Config) -> None:
    for course_id, course_data in config.courses_data.courses.items():
        BUTT_COURSES[str(course_id)] = course_data.name
        if 'pragmatic' in course_data.templates.get('male'):
            BUTT_COURSES_PRAGMATIC[str(course_id)] = course_data.name

BUTTS_URL_PROMO: dict[str, str] = {
    'Лучший по Python.Часть 3':
        'https://stepik.org/a/227627/pay?promo=90e83ebae76d239a',
    'Лучший по Python. Часть 4':
        'https://stepik.org/a/241971/pay?promo=c9af0a0dae2667f9'}
BUTTS_PROMO_OTHER_AUTHOR: dict[str, str] = {
    'courses_joseph_dzeranov': 'Курсы Иосифа Дзеранова',
    'courses_pragmatic_programmer': 'Курсы Pragmatic Programmer'}

BUTT_WANT_PROMOCODE_DZERANOV: dict[str, str] = {
    'want_promocode_dzeranov': 'Хочу промокод на другой курс Иосифа'}
BUTTS_URL_DZERANOV_PROMOCODES: dict[str, str] = {
    'Основы программирования':
        'https://stepik.org/a/5482/pay?promo=1edbb8dbd308b025',
    'Для продвинутых':
        'https://stepik.org/a/84983/pay?promo=8a521ae326d8d861',
    'База':
        'https://stepik.org/a/107779/pay?promo=071d0011effc70fc',
    'Алгоритмы и структуры данных':
        'https://stepik.org/a/120862/pay?promo=47ac21e1ed03f8a9',
    'Профессия Backend разработчик':
        'https://stepik.org/a/170073/pay?promo=2cbd97b40850a6b8',
    'Профессия Разработчик Telegram ботов':
        'https://stepik.org/a/210117/pay?promo=ddd841822fd96625',
    }

BUTTS_URL_PRAGMATIC_PROGER: dict[str, str] = {
    'Пакет курсов. Базы данных и SQL с нуля до профи':
        'https://stepik.org/a/212383/pay?promo=daafd6aae3c80832',
    'Программа. Linux: с нуля до сертификата':
        'https://stepik.org/a/198983/pay?promo=3a1ad92510369e8e',
    'IT база SQL + Linux + Git':
        'https://stepik.org/a/253025/pay?promo=f941b669d9b68e5f',
    'Git + GitHub. Полный курс':
        'https://stepik.org/a/214865/pay?promo=092acaeeece1d6d9'
    }
