import logging
import re

from datetime import datetime, timedelta

from aiogram.enums import ChatType, ContentType
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config_data.config import Config
from keyboards.buttons import BUTT_COURSES_PRAGMATIC
from utils import get_username
from utils.utils import MessageProcessor

logger_filters = logging.getLogger(__name__)


class IsPragmaticCoursesFilter(BaseFilter):
    async def __call__(self, clbk: CallbackQuery) -> bool:
        """Checks if the callback data is in the list of allowed courses."""
        return clbk.data in BUTT_COURSES_PRAGMATIC


class IsBestPythonCoursesFilter(BaseFilter):
    async def __call__(self, clbk: CallbackQuery, config: Config) -> bool:
        logger_filters.debug('Entry')

        logger_filters.debug(f'{clbk.data=}')
        logger_filters.debug(f'{config.courses_data.best_in_python_courses=}')

        callback_data = clbk.data
        if callback_data is None:
            return False

        if not callback_data.isdigit():
            return False

        return int(callback_data) in config.courses_data.best_in_python_courses


class CallBackFilter(BaseFilter):
    """Checks if callback_data is present in the allowed list."""

    def __init__(self, clbk_data: str, *args: str) -> None:
        self.allowed_data: tuple = (clbk_data, *args)

    async def __call__(self, clbk: CallbackQuery) -> bool:
        """Checks if callback.data is in the list of allowed values"""
        return clbk.data in self.allowed_data


class IsPrivateChat(BaseFilter):
    """Checks if the chat is private."""

    async def __call__(self, msg: Message) -> bool:
        return msg.chat.type == ChatType.PRIVATE


class IsValidProfileLink(BaseFilter):
    """Проверяет, содержит ли сообщение валидную ссылку на профиль,
    где цифры в URL это ID пользователя. Поддерживает:
    1. Ссылки внутри текста с пробелами/переносами
    2. Форматы:
       - https://stepik.org/users/USER_ID
       - https://stepik.org/users/USER_ID/profile
       - https://stepik.org/users/USER_ID/
    """

    async def __call__(
        self, msg: Message, state: FSMContext
    ) -> bool | dict[str, str]:
        msg_processor = MessageProcessor(msg, state)

        if not msg.text:
            logger_filters.warning('Message text is empty')
            return False
        elif not msg.from_user:
            logger_filters.warning('User info is empty')
            return False

        text = msg.text.strip()

        # Looks for a link anywhere in the text
        match = re.search(
            r'\bhttps?://[^\s/]+/users/(\d+)(?:/profile)?/?\b',
            text,
            re.IGNORECASE,
        )

        if match:
            stepik_user_id = match.group(1)
            return {'stepik_user_id': stepik_user_id}

        await msg_processor.save_msg_id(value=msg, msgs_for_del=True)

        logger_filters.warning(
            f'Ссылка не корректна:{msg.from_user.id}'
            f':{await get_username(msg)}:[{msg.text}]'
        )

        value = await msg.answer(
            f'{await get_username(msg)}, ваша ссылка на профиль не корректна, '
            f'попробуйте еще раз.'
        )

        await msg_processor.deletes_msg_a_delay(
            value, delay=7, indication=True
        )
        return False


class IsAdmins(BaseFilter):
    async def __call__(self, msg: Message, config: Config) -> bool:
        logger_filters.debug('Entry')

        if not msg.from_user:
            logger_filters.warning('User info is empty')
            return False

        user_id = str(msg.from_user.id)
        admins_id = config.tg_bot.id_admins
        logger_filters.debug(f'{admins_id=}')

        logger_filters.debug('Exit')
        return user_id in admins_id


class IsFullName(BaseFilter):
    async def __call__(
        self,
        msg: Message,
        state: FSMContext,
        msg_processor: MessageProcessor,
    ) -> bool | dict:
        logger_filters.debug(f'Entry {self.__class__.__name__}')

        if (
            msg.content_type != ContentType.TEXT
            or not msg.text
            or not msg.from_user
        ):
            logger_filters.warning(
                'Invalid message format, missing text or user info'
            )
            if msg.content_type != ContentType.TEXT:
                await self._delete_and_notify(msg, msg_processor)
            return False

        text = msg.text.strip()
        user_id = msg.from_user.id
        username = await get_username(msg)

        if len(text) > 30:
            await self._delete_and_notify(
                msg,
                msg_processor,
                message='Длина ФИО больше 30-ти символов 😮',
            )
            return False

        words = text.split()

        if len(words) < 2:
            logger_filters.warning(
                f'Некорректные ФИО от {user_id}: {username}. Введено: {text}'
            )
            await self._delete_and_notify(
                msg,
                msg_processor,
                message='Введите хотя бы два слова: Имя и Фамилию 😉',
            )
            return False

        pattern = r"""
            ^
            [ёа-яa-z]+(?:-[ёа-яa-z]+)?
            (?:\s+[ёа-яa-z]+(?:-[ёа-яa-z]+)?)+
            $
        """

        if re.fullmatch(
            pattern, text, flags=re.VERBOSE | re.IGNORECASE
        ) and not any(char.isdigit() for char in text):
            capitalized_words = [
                '-'.join(part.capitalize() for part in word.split('-'))
                for word in words
            ]
            logger_filters.debug(f'Exit {self.__class__.__name__}')
            return {'full_name': ' '.join(capitalized_words)}

        # Если регулярка не прошла
        logger_filters.warning(
            f'Некорректные ФИО от {user_id}: {username}. Введено: {text}'
        )
        await self._delete_and_notify(
            msg, msg_processor, message='Некорректно введены данные'
        )
        return False

    @staticmethod
    async def _delete_and_notify(
        msg: Message,
        msg_processor: MessageProcessor,
        message: str | None = None,
    ) -> None:
        """Deletes a message and sends a notification"""
        await msg.delete()

        if message:
            response = await msg.answer(
                f'{await get_username(msg)}, {message}'
            )
            await msg_processor.deletes_msg_a_delay(
                response, delay=7, indication=True
            )


class IsCorrectData(BaseFilter):
    async def __call__(
        self, msg: Message, state: FSMContext, msg_processor: MessageProcessor
    ) -> bool | dict[str, str]:
        logger_filters.debug(f'Entry {self.__class__.__name__}')
        username = await get_username(msg)

        if msg.content_type != ContentType.TEXT:
            await msg.delete()
            return False

        if not msg.text:
            logger_filters.debug(f'Exit False {self.__class__.__name__}')
            await msg.delete()
            return False

        start_course = datetime.strptime('01.03.2024', '%d.%m.%Y')
        date_str = msg.text.strip()
        logger_filters.debug(f'{date_str=}')

        try:
            date_obj = datetime.strptime(date_str, '%d.%m.%Y')
            if date_obj.date() < start_course.date():
                await msg.delete()
                value = await msg.answer(
                    f'{username}, вы указали дату, когда курс еще не был '
                    f'создан)'
                )
                await msg_processor.deletes_msg_a_delay(
                    value, delay=6, indication=True
                )
                return False

            server_date = datetime.now().date()
            if date_obj.date() > (server_date + timedelta(days=1)):
                await msg.delete()
                value = await msg.answer(
                    f'{username}, вы указали дату из будущего.\n'
                    f'Пожалуйста, повторите.'
                )
                await msg_processor.deletes_msg_a_delay(
                    value, delay=6, indication=True
                )
                return False

            logger_filters.debug(f'Exit Done {self.__class__.__name__}')
            return {'date': date_str}

        except ValueError:
            logger_filters.warning(
                f'Некорректная дата:{username}:{msg.from_user}:[{date_str}]'
            )
            logger_filters.debug(f'Exit False {self.__class__.__name__}')
            await msg.delete()
            value = await msg.answer(
                'Неверный формат даты. Пожалуйста, введите дату в формате '
                'ДД.ММ.ГГГГ'
            )
            await msg_processor.deletes_msg_a_delay(value, 5, indication=True)
            return False


class IsCorrectEmail(BaseFilter):
    async def __call__(self, msg: Message) -> bool:
        """Проверяет валидность email по регулярному выражению.
        Покрывает большинство повседневных случаев, но не проверяет
        существование домена.
        """

        if msg.content_type != ContentType.TEXT:
            await msg.delete()
            logger_filters.warning('Content type is not TEXT')
            return False
        if not msg.text:
            logger_filters.warning('Message text is empty')
            return False

        email = msg.text.strip()
        pattern = r"""
                ^
                [a-zA-Z0-9_.+-]+
                @
                [a-zA-Z0-9-]+
                (\.[a-zA-Z0-9-]+)*
                \.[a-zA-Z]{2,}
                $
            """
        if re.fullmatch(pattern, email, re.VERBOSE):
            return True
        else:
            await msg.delete()
            return False
