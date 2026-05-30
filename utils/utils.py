import asyncio
import io
import logging
import os
import re

from dataclasses import dataclass
from datetime import datetime, timedelta

from aiogram.client.session import aiohttp
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    ChatFullInfo,
    FSInputFile,
    LinkPreviewOptions,
    Message,
    Update,
)
from PyPDF2 import PdfReader, PdfWriter
from redis.asyncio import Redis
from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from config_data.config import Config, Course

logger_utils = logging.getLogger(__name__)

# Создаем пул потоков для выполнения синхронных операций
# executor = ThreadPoolExecutor(max_workers=4)


async def check_user_in_group(
    _type_update: Message | CallbackQuery, tg_target_channel: int
) -> bool:
    logger_utils.debug('Entry')

    target_chat = tg_target_channel
    user_id = _type_update.from_user.id
    logger_utils.debug(f'{user_id=}')
    try:
        chat_member = await _type_update.bot.get_chat_member(
            target_chat, user_id
        )
        # logger_utils.debug(f'{chat_member=}')
        try:
            status: bool = chat_member.is_member
            logger_utils.debug(f'{status=}')
        except Exception:
            status = chat_member.status in {
                'member',
                'administrator',
                'creator',
            }
            logger_utils.debug(f'{status=}')
        else:
            logger_utils.debug('Exit')
            return status

    except Exception as err:
        logger_utils.debug(f'{err=}')
        return False

    else:
        logger_utils.debug('Exit')
        return status


async def get_username(
    _type_update: Message | CallbackQuery | ChatFullInfo,
) -> str:
    """ """
    if isinstance(_type_update, ChatFullInfo):
        if username := _type_update.username:
            return f'@{username}'
        elif first_name := _type_update.first_name:
            return first_name
        return str(_type_update.id)

    if username := _type_update.from_user.username:
        return f'@{username}'
    elif first_name := _type_update.from_user.first_name:
        return first_name
    return str(_type_update.from_user.id)


@dataclass
class StepikService:
    client_id: str
    client_secret: str
    redis_client: Redis
    courses: dict[int, Course]

    async def is_private_account(self, stepik_user_id: str):
        logger_utils.info(
            f'Проверка Stepik-аккаунта юзера на приватность:'
            f'Stepik_ID:{stepik_user_id}'
        )
        url = f'https://stepik.org/api/users/{stepik_user_id}'
        try:
            access_token = await self.get_stepik_access_token()
            headers = {'Authorization': f'Bearer {access_token}'}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        users = response_data.get('users')
                        logger_utils.debug(f'{users=}')
                        if users:
                            is_private = users[0]['is_private']
                            logger_utils.info(
                                f'Stepik_ID:{stepik_user_id}:'
                                f'{"Приватный" if is_private else "Публичный"}'
                            )
                            return True if is_private else False
                        else:
                            logger_utils.warning(
                                f'Данные юзера не найдены для'
                                f' stepik_id:{stepik_user_id} из-за '
                                f'приватности аккаунта.'
                            )
                    else:
                        logger_utils.error(
                            f'Неожиданный статус ответа: {response.status}',
                            exc_info=True,
                        )
        except Exception as err:
            logger_utils.error(
                f'Ошибка при проверке приватности аккаунта'
                f' пользователя: {err}',
                exc_info=True,
            )

    async def get_stepik_access_token(self) -> str:
        """
        Получает токен доступа для Stepik API.
        :return str: Токен доступа
        :raises: RuntimeError, если не удалось получить токен.
        """
        cached_token = await self.redis_client.get('stepik_token')
        url = 'https://stepik.org/oauth2/token/'

        if cached_token:
            logger_utils.info('Используется кэшированный токен из Redis.')
            return cached_token

        data = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, data=data, allow_redirects=True
                ) as resp:
                    if resp.status != 200:
                        error_message = await resp.text()
                        logger_utils.error(
                            f'Ошибка при запросе токена: {error_message}',
                            exc_info=True,
                        )
                        raise RuntimeError(
                            f'Не удалось получить токен: {error_message}'
                        )
                    response = await resp.json()
                    access_token = response.get('access_token')
                    if not access_token:
                        raise RuntimeError('Токен не найден в ответе API.')
                    # Сохраняем токен в Redis с TTL
                    await self.redis_client.set(
                        'stepik_token', access_token, ex=35000
                    )
                    logger_utils.info(
                        'Токен успешно получен и сохранён в Redis.'
                    )
                    return access_token

        except aiohttp.ClientError as err:
            logger_utils.error(
                f'Ошибка сети при запросе токена: {err}', exc_info=True
            )
            raise RuntimeError(f'Ошибка сети: {err}')

        except Exception as err:
            logger_utils.error(
                f'Неожиданная ошибка при запросе токена: {err}', exc_info=True
            )
            raise RuntimeError(f'Неожиданная ошибка: {err}')

    async def check_cert_in_user(
        self, tg_user_id: str, course_id: str
    ) -> bool | str:
        """
        Проверяет, есть ли номер сертификата у пользователя.
        :param course_id:
        :param tg_user_id: ID пользователя.
        :return: True и номер сертификата, если найден, иначе False.
        """
        data = await self.redis_client.hgetall(name=tg_user_id)
        logger_utils.debug(f'{data=}')

        certificate = await self.redis_client.hget(
            f'{tg_user_id}', f'{course_id}'
        )
        return certificate if certificate else False

    async def save_certificate_number(self, user_id: str, course_id: str):
        """
        Сохраняет номер сертификата в Redis.
        :param course_id: ID курса.
        :param user_id: tg_ID пользователя.
        """

        try:
            await self.redis_client.hset(f'{user_id}', course_id)
            logger_utils.info(f'Данные сохранены: {user_id}')
        except Exception as err:
            logger_utils.error(
                f'Ошибка при сохранении данных в Redis: {err}', exc_info=True
            )

    async def check_cert_in_stepik(
        self,
        stepik_user_id: str,
        course_id: str,
        access_token: str,
        tg_username: str,
        config: Config,
    ) -> bool | str:
        """
         Проверяет наличие сертификата у пользователя на Stepik.
        :param config:
        :param tg_username:
        :param stepik_user_id: ID пользователя на Stepik.
        :param course_id: ID курса, сертификат которого надо проверить на
               наличие у ученика.
        :param access_token: Токен доступа Stepik API.
        :return: 'PRIVATE' если аккаунт ученика на Stepik приватный;
                  True, если сертификат найден, иначе False.
        """
        if await self.is_private_account(stepik_user_id):
            return 'PRIVATE'

        page_number = 1
        while True:
            try:
                api_url = (
                    f'https://stepik.org/api/certificates?user='
                    f'{stepik_user_id}&page={page_number}'
                )
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        api_url,
                        headers={'Authorization': 'Bearer ' + access_token},
                    ) as response:
                        if response.status == 429:
                            logger_utils.warning(
                                'Превышен лимит запросов. Ожидание… 10c'
                            )
                            await asyncio.sleep(10)
                        response.raise_for_status()
                        data = await response.json()
                        # logger_utils.debug(f'{data['certificates']}')

                        # Проверяем сертификаты на текущей странице
                        course_data = config.courses_data.courses.get(
                            int(course_id)
                        )
                        for certificate in data['certificates']:
                            if certificate['course'] == int(course_id):
                                logger_utils.info(
                                    f'У STEPIK_ID:{stepik_user_id},'
                                    f'TG_USERNAME:{tg_username} '
                                    f'cертификат курса {course_data.name}'
                                    f':{course_id} имеется на Stepik'
                                )
                                return True  # Сертификат за курс найден

                        # Если есть следующая страница, переходим к ней
                        if data['meta']['has_next']:
                            page_number += 1
                            await asyncio.sleep(1)  # Задержка между запросами
                        else:
                            break  # Больше страниц нет
            except Exception as err:
                logger_utils.error(
                    f'Ошибка при запросе сертификатов: {err}', exc_info=True
                )
                raise
        return False  # Сертификат за курс не найден

    def sync_generate_certificate(
        self, data: dict[str, str], w_text: bool = False
    ) -> tuple[str, str] | None:
        """
        Синхронная функция для генерации сертификата.
        :param data: Данные для генерации сертификата.
        :param w_text: Флаг для добавления водяного знака.
        :return: Путь к сгенерированному файлу сертификата.
        """
        logger_utils.debug('Entry')

        try:
            # 1. Извлечение данных из data
            user_name = data.get('full_name')
            number = data.get('end_number')
            course_id = int(data.get('course'))
            gender = data.get('gender')

            # Проверка значений gender
            if gender not in ('female', 'male'):
                logger_utils.error(f'Неизвестное значение gender: {gender}')
                raise ValueError(f'Неизвестное значение gender: {gender}')

        except (KeyError, TypeError, ValueError) as err:
            logger_utils.error(
                f'Ошибка при извлечении данных из state_data: {err}',
                exc_info=True,
            )
            return None

        # 2. Определение путей к файлам
        try:
            local_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', 'static')
            )
            base_dir = os.getenv('CERTIFICATE_DATA_DIR', local_path)

            course_config = self.courses.get(course_id)
            if not course_config:
                logger_utils.error(
                    f'Конфигурация для курса {course_id} не найдена.'
                )
                raise ValueError(f'Неизвестный ID курса: {course_id}')

            template_name = course_config.templates.get(gender)
            if not template_name:
                logger_utils.error(
                    f'Шаблон для курса {course_id} и'
                    f' гендера {gender} не найден.'
                )
                raise ValueError(
                    f'Шаблон не найден для gender={gender}, course={course_id}'
                )

            # Проверка, что template_name не равен None
            if template_name is None:
                logger_utils.error(
                    f'Не удалось определить шаблон для gender={gender},'
                    f' course={course_id}'
                )
                raise ValueError('Имя шаблона не может быть None')

            logger_utils.debug(f'Выбран шаблон: {template_name}')

            font_path = os.path.join(base_dir, 'Bitter-Regular.ttf')
            template_file = os.path.join(base_dir, template_name)

            course_name = course_config.name.replace(' ', '_')
            output_file = os.path.join(base_dir, f'{course_name}_{number}.pdf')

            if not os.path.exists(font_path):
                raise FileNotFoundError(f'Файл шрифта не найден: {font_path}')

        except FileNotFoundError as err:
            logger_utils.error(
                f'Ошибка при определении путей: {err}', exc_info=True
            )
            return None
        except Exception as err:
            logger_utils.error(
                f'Неизвестная ошибка при определении путей: {err}',
                exc_info=True,
            )
            return None

        # 3. Регистрация шрифта
        try:
            pdfmetrics.registerFont(TTFont('BitterReg', font_path))
        except Exception as err:
            logger_utils.error(
                f'Ошибка при регистрации шрифта: {err}', exc_info=True
            )
            return None

        # 4. Работа с PDF
        try:
            light_gray = Color(230 / 255, 230 / 255, 230 / 255)
            watermark_text = 'TEST VERSION'
            reader = PdfReader(template_file)
            writer = PdfWriter()

            for page_num in range(len(reader.pages)):
                page = reader.pages[page_num]
                packet = io.BytesIO()
                can = canvas.Canvas(packet, pagesize=letter)
                font_size = 16

                if len(user_name) in (24, 25):
                    font_size = 15
                elif len(user_name) in (26, 27):
                    font_size = 14
                elif len(user_name) in (28, 29, 30):
                    font_size = 13

                text_width = can.stringWidth(user_name, 'BitterReg', font_size)
                can.setFont('BitterReg', font_size)
                page_width = letter[0]
                x_position = (page_width - text_width) / 2 + 155
                can.drawString(x_position, 306, user_name)
                can.setFont('BitterReg', 21)
                can.setFillColor(light_gray)
                can.drawString(440, 373, number)

                if w_text:
                    can.setFillColor(Color(0.3, 0, 0, alpha=0.7))
                    can.setFont('Helvetica', 50)
                    can.rotate(45)
                    can.drawString(110, 60, watermark_text)

                can.showPage()
                can.save()
                packet.seek(0)
                new_pdf = PdfReader(packet)
                page.merge_page(new_pdf.pages[0])
                writer.add_page(page)

            with open(output_file, 'wb') as fh:
                writer.write(fh)

        except Exception as err:
            logger_utils.error(
                f'Ошибка при работе с PDF: {err}', exc_info=True
            )
            return None

        # 5. Возврат результата
        return output_file, template_name

    def sync_exists_certificate(
        self, data: dict[str, str], w_text: bool = False
    ):
        logger_utils.debug('Entry')
        logger_utils.debug(f'{data=}')

        try:
            local_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', 'static')
            )
            base_dir = os.getenv('CERTIFICATE_DATA_DIR', local_path)

            template_name = data.get('template_name')
            user_name = data.get('full_name')
            cert_number = data.get('cert_number')

            font_path = os.path.join(base_dir, 'Bitter-Regular.ttf')
            template_file = os.path.join(base_dir, template_name)
            course_id = int(data.get('course'))
            course_data = self.courses.get(course_id)
            course_name = course_data.name.replace(' ', '_')
            output_file = os.path.join(
                base_dir, f'{course_name}_{cert_number}.pdf'
            )

            if not os.path.exists(font_path):
                raise FileNotFoundError(f'Файл шрифта не найден: {font_path}')
        except FileNotFoundError as err:
            logger_utils.error(
                f'Ошибка при определении путей: {err}', exc_info=True
            )
            return None
        except Exception as err:
            logger_utils.error(
                f'Неизвестная ошибка при определении путей: {err}',
                exc_info=True,
            )
            return None

        # 3. Регистрация шрифта
        try:
            pdfmetrics.registerFont(TTFont('BitterReg', font_path))
        except Exception as err:
            logger_utils.error(
                f'Ошибка при регистрации шрифта: {err}', exc_info=True
            )
            return None

        # 4. Работа с PDF
        try:
            light_gray = Color(230 / 255, 230 / 255, 230 / 255)
            watermark_text = 'TEST VERSION'
            reader = PdfReader(template_file)
            writer = PdfWriter()

            for page_num in range(len(reader.pages)):
                page = reader.pages[page_num]
                packet = io.BytesIO()
                can = canvas.Canvas(packet, pagesize=letter)
                font_size = 16

                if len(user_name) in (24, 25):
                    font_size = 15
                elif len(user_name) in (26, 27):
                    font_size = 14
                elif len(user_name) in (28, 29, 30):
                    font_size = 13

                text_width = can.stringWidth(user_name, 'BitterReg', font_size)
                can.setFont('BitterReg', font_size)
                page_width = letter[0]
                x_position = (page_width - text_width) / 2 + 155
                can.drawString(x_position, 306, user_name)
                can.setFont('BitterReg', 21)
                can.setFillColor(light_gray)
                can.drawString(440, 373, cert_number)

                if w_text:
                    can.setFillColor(Color(0.3, 0, 0, alpha=0.7))
                    can.setFont('Helvetica', 50)
                    can.rotate(45)
                    can.drawString(110, 60, watermark_text)

                can.showPage()
                can.save()
                packet.seek(0)
                new_pdf = PdfReader(packet)
                page.merge_page(new_pdf.pages[0])
                writer.add_page(page)

            with open(output_file, 'wb') as fh:
                writer.write(fh)
        except Exception as err:
            logger_utils.error(
                f'Ошибка при работе с PDF: {err}', exc_info=True
            )
            return None
        # 5. Возврат результата
        return output_file

    async def generate_certificate(
        self,
        state_data: FSMContext,
        type_update,
        w_text: bool = False,
        exist_cert=False,
    ):
        """
        Асинхронная обёртка для генерации сертификата.
        :param type_update: Тип апдэйта.
        :param exist_cert: Флаг существования сертификата.
        :param state_data: Данные для генерации сертификата.
        :param w_text: Флаг для добавления водяного знака.
        :return: Путь к сгенерированному файлу сертификата.
        """
        logger_utils.debug('Entry')

        data = await state_data.get_data()
        user_tg_id = str(type_update.from_user.id)

        if exist_cert:
            course_id = str(type_update.data)
            try:
                user_data = await self.redis_client.hget(user_tg_id, course_id)
                logger_utils.debug(f'{user_data=}')

                cert_number, full_name, template = user_data.split(':')
                logger_utils.debug(f'{cert_number}-{full_name}-{template}')
                data.update(
                    {
                        'template_name': template,
                        'cert_number': cert_number,
                        'full_name': full_name,
                        'course': course_id,
                    }
                )

            except Exception:
                logger_utils.error(
                    'Не удалось получить данные пользователя '
                    'из Redis хранилища',
                    exc_info=True,
                )
                raise
            output_file = await asyncio.to_thread(
                self.sync_exists_certificate, data, w_text
            )
            logger_utils.debug('Exit')
            return output_file

        course_id = data.get('course')
        try:
            # Выполняем синхронную операцию в отдельном потоке
            output_file, template_name = await asyncio.to_thread(
                self.sync_generate_certificate, data, w_text
            )
            cert_number = await state_data.get_value('end_number')
            full_name = await state_data.get_value('full_name')

            # Сохраняем данные в Redis
            await self.redis_client.hset(
                name=user_tg_id,
                key=course_id,
                value=f'{cert_number}:{full_name}:{template_name}',
            )
            logger_utils.debug(
                f'Данные сохранены в Redis: '
                f'user_tg_id={user_tg_id},'
                f' course_id={course_id}'
            )

            logger_utils.debug('Exit')
            return output_file

        except Exception as err:
            logger_utils.error(f'{err=}', exc_info=True)
            logger_utils.debug('Exit')
            raise

    async def send_certificate(
        self,
        clbk: CallbackQuery,
        output_file: str,
        state: FSMContext,
        course_id: str,
        is_copy=False,
    ) -> None:
        """
        Отправляет сертификат пользователю, и удаляет файл после отправки.
        :param course_id: IG курса на Stepik
        :param is_copy: Флаг True, если отправляется копия.
        :param state: Контекст состояний.
        :param clbk: CallbackQuery от пользователя.
        :param output_file: Путь к файлу сертификата.
        """
        msg_processor = MessageProcessor(clbk, state)
        try:
            if not output_file:
                logger_utils.error('Получен пустой путь к файлу сертификата.')
                await clbk.message.answer(
                    'Проблем при отправке сертификата.\n'
                    'Обратитесь к администратору.'
                )
                return

            # Проверяем, существует ли файл
            if not os.path.exists(output_file):
                logger_utils.error(f'Файл {output_file} не найден.')
                return

            pdf_file = FSInputFile(output_file)

            # Отправка файла пользователю
            await clbk.message.answer_document(
                pdf_file,
                caption='Ваш сертификат готов! 🎉\n'
                'Желаем удачи в дальнейшем'
                ' обучении!🤓',
            )
            user_data = await self.redis_client.hget(
                str(clbk.from_user.id), course_id
            )
            user_info_data = (
                f'TG_ID:{clbk.from_user.id}:'
                f'{await get_username(clbk)}:{user_data}'
            )
            if is_copy:
                logger_utils.info(f'Выдана копия для {user_info_data}')
            else:
                logger_utils.info(f'Выдан сертификат {user_info_data}')

        except Exception as err:
            logger_utils.error(
                f'Ошибка при отправке файла: {err=}', exc_info=True
            )
            value = await clbk.message.answer(
                'Что-то пошло не так, сообщите администратору.'
            )
            await msg_processor.save_msg_id(value, msgs_for_del=True)
        finally:
            # Удаляем файл после отправки
            try:
                os.remove(output_file)
                logger_utils.debug(f'Файл {output_file} удалён.')
            except Exception as err:
                logger_utils.error(
                    f'Ошибка при удалении файла {output_file}: '
                    f'{err.__class__.__name__}',
                    exc_info=True,
                )


@dataclass
class MessageProcessor:
    """
    Class for managing and processing chat messages.
    _message (Message | CallbackQuery): The message or callback query object.
    _state (FSMContext): The finite state machine context.
    """

    _type_update: Message | CallbackQuery
    _state: FSMContext

    async def deletes_messages(
        self, msgs_for_del=False, msgs_remove_kb=False
    ) -> None:
        """
        Deleting messages from a chat based on passed parameters.
        This method removes various types of messages from a chat.
        Messages are deleted only if the corresponding parameters
        are set to True.
        If no parameters are specified, the method does not perform any actions.
        :param msgs_for_del:
        :param msgs_remove_kb:
        :return: None
        """
        logger_utils.debug('Entry')
        chat_id = None
        if isinstance(self._type_update, Message):
            chat_id = self._type_update.chat.id
        elif isinstance(self._type_update, CallbackQuery):
            if self._type_update.message:
                chat_id = self._type_update.message.chat.id
            else:
                logger_utils.error('CallbackQuery does not contain a message.')
                return
        elif isinstance(self._type_update, Update):
            if self._type_update.message:
                chat_id = self._type_update.message.chat.id
            elif (
                self._type_update.callback_query
                and self._type_update.callback_query.message
            ):
                chat_id = self._type_update.callback_query.message.chat.id
            else:
                logger_utils.error(
                    'Update does not contain a valid chat or message.'
                )
                return

        kwargs: dict = {
            'msgs_for_del': msgs_for_del,
            'msgs_remove_kb': msgs_remove_kb,
        }

        keys = None
        try:
            keys = [key for key, val in kwargs.items() if val]
        except Exception as err:
            logger_utils.error(f'{err.__class__.__name__}', exc_info=True)
        logger_utils.debug(f'{keys=}')

        if msgs_remove_kb:
            await self.removes_inline_kb(chat_id=chat_id)

        if keys:
            for key in keys:
                msgs_ids: list = dict(await self._state.get_data()).get(
                    key, []
                )
                logger_utils.debug('Starting to delete messages…')

                for msg_id in set(msgs_ids):
                    try:
                        await self._type_update.bot.delete_message(
                            chat_id=chat_id, message_id=msg_id
                        )
                    except Exception as err:
                        logger_utils.warning(
                            f'Failed to delete message ID:{msg_id}:{err}'
                        )
                await self._state.update_data({key: []})

        logger_utils.debug('Exit')

    async def save_msg_id(
        self,
        value: Message | CallbackQuery,
        msg_remove: str | None = None,
        msgs_for_del=False,
        msgs_remove_kb=False,
    ) -> None:
        """
        :param msg_remove: key for remove message on ID.
        :param value: Message | CallbackQuery.
        :param msgs_for_del:
        :param msgs_remove_kb:
        :return: None
        """
        logger_utils.debug('Entry')
        if key := msg_remove:
            await self._state.update_data(
                {key: str(self._type_update.message_id)}
            )

        flags: dict = {
            'msgs_for_del': msgs_for_del,
            'msgs_remove_kb': msgs_remove_kb,
        }

        for key, val in flags.items():
            logger_utils.debug('Start writing data to storage…')
            if val:
                data: list = dict(await self._state.get_data()).get(key, [])
                if value.message_id not in data:
                    data.append(str(value.message_id))
                    logger_utils.debug('Msg ID to recorded')
                logger_utils.debug('No msg ID to record')
                await self._state.update_data({key: data})
        logger_utils.debug('Exit')

    async def removes_inline_kb(self, chat_id, key='msgs_remove_kb') -> None:
        """
        Removes built-in keyboards from messages.
        This function gets message IDs from the state and removes
        built-in keyboards from these messages. After removing the keyboards,
        the state is updated to clear the list of message IDs.
        Logs:
            — Start the keyboard removal process.
            — Errors when removing the keyboard.
            — Successful completion of the keyboard removal process.
        :param chat_id:
        :param key: Str
        :return: None
        """
        logger_utils.debug('Entry')

        msgs: list = dict(await self._state.get_data()).get(key, [])
        for msg_id in set(msgs):
            try:
                await self._type_update.bot.edit_message_reply_markup(
                    chat_id=chat_id, message_id=msg_id
                )
            except TelegramBadRequest as err:
                logger_utils.error(f'{err}', stack_info=True)
            logger_utils.debug(f'Keyboard removed for id:{msg_id}')
        await self._state.update_data({key: []})

        logger_utils.debug('Exit')

    async def delete_message(self, key='msg_del_on_key') -> None:
        """
        Удаляет сообщение, используя указанный ключ. Метод извлекает данные из
        состояния и использует их для удаления сообщения с указанным ключом.
        Args: key (str): Ключ, по которому будет найдено сообщение
        удаление. По умолчанию «msg_id_for_del». Возвращает: None.
        :param key: str
        :return: None
        """
        logger_utils.debug('Entry')
        try:
            chat_id = None
            data = await self._state.get_data()
            if isinstance(self._type_update, Message):
                chat_id = self._type_update.chat.id
            elif isinstance(self._type_update, CallbackQuery):
                if self._type_update.message:
                    chat_id = self._type_update.message.chat.id
                else:
                    logger_utils.error(
                        'CallbackQuery does not contain a message.'
                    )
                    return
            elif isinstance(self._type_update, Update):
                if self._type_update.message:
                    chat_id = self._type_update.message.chat.id
                elif (
                    self._type_update.callback_query
                    and self._type_update.callback_query.message
                ):
                    chat_id = self._type_update.callback_query.message.chat.id
                else:
                    logger_utils.error(
                        'Update does not contain a valid chat or message.'
                    )
                    return
            await self._type_update.bot.delete_message(
                chat_id=chat_id, message_id=data.get(key)
            )
        except Exception as err:
            logger_utils.error(f'{err=}', exc_info=True)
        logger_utils.debug('Exit')

    @staticmethod
    async def deletes_msg_a_delay(
        value: Message, delay: int = 1, indication=False
    ) -> None:
        if not indication:
            await asyncio.sleep(delay)
            await value.delete()
            return

        # Сохраняем оригинальный текст сообщения
        original_text = value.text
        try:
            if indication:
                # Обратный отсчет от delay до 1
                for remaining in range(delay, 0, -1):
                    try:
                        # Обновляем текст сообщения с оставшимся временем
                        await value.edit_text(
                            f'{original_text}\n\nУдалится через: {remaining} сек...'
                        )
                    except Exception as e:
                        logger_utils.warning(
                            f'Не удалось отредактировать сообщение: {e}'
                        )
                    await asyncio.sleep(1)
        except Exception as e:
            logger_utils.error(
                f'Ошибка в deletes_msg_a_delay: {e}', exc_info=True
            )
        finally:
            try:
                await value.delete()
            except Exception as e:
                logger_utils.warning(f'Не удалось удалить сообщение: {e}')

    async def send_message_with_delay(
        self,
        chat_id: int,
        text: str,
        delay: int,
        keyboard=None,
        preview_link: str = None,
        disable_web_page_preview: bool = None,
    ) -> Message:
        """
        Sends a message with a specified delay.
        :param keyboard:
        :param disable_web_page_preview:
        :param chat_id: The ID of the chat where the message will be sent.
        :param text:
        :param delay: The delay in seconds before sending the message.
        :param preview_link: Link for a preview.
        :return Message: Message: The sent message object.
        """
        logger_utils.debug('Entry')
        await asyncio.sleep(delay)

        preview_link_option = LinkPreviewOptions(url=preview_link)
        message = await self._type_update.bot.send_message(
            chat_id=chat_id,
            reply_markup=keyboard,
            text=text,
            link_preview_options=preview_link_option if preview_link else None,
            disable_web_page_preview=disable_web_page_preview,
        )

        logger_utils.debug('Exit')
        return message


async def shifts_the_date_forward(days: int = 10):
    expire_date = datetime.now() + timedelta(days=days)
    months: dict[int, str] = {
        1: 'января',
        2: 'февраля',
        3: 'марта',
        4: 'апреля',
        5: 'мая',
        6: 'июня',
        7: 'июля',
        8: 'августа',
        9: 'сентября',
        10: 'октября',
        11: 'ноября',
        12: 'декабря',
    }
    return f'{expire_date.day} {months[expire_date.month]}'


async def get_data_users(clbk: CallbackQuery, redis_data: Redis):
    cursor = '0'
    user_ids = []
    while cursor:
        cursor, keys = await redis_data.scan(cursor, match='*')
        user_ids.extend([key for key in keys if re.match(r'^\d{9,10}$', key)])
    logger_utils.debug(f'{user_ids=}')

    courses: dict = {'214271': 1, '221885': 2, '227627': 3, '241971': 4}
    data_users: dict[int, list] = {}
    for user in user_ids:
        chat_data = await clbk.bot.get_chat(int(user))
        username = await get_username(chat_data)
        _, data = await redis_data.hscan(user)
        logger_utils.debug(f'{data=}')
        try:
            keys = data.keys()
            logger_utils.debug(f'{keys=}')
        except Exception as err:
            logger_utils.error(
                f'Ошибка чтения ключа:DB-№2 {err}', exc_info=True
            )
        else:
            for key in keys:
                data_users.setdefault(key, []).append(username)
    logger_utils.debug(f'{data_users=}')
    text = ''
    for num_course, users in data_users.items():
        qt_users = len(users)
        user_names = '\n'.join(users)
        text += (
            f'<code>Курс №{courses[num_course]} прошли {qt_users}:</code>\n'
            f'{user_names}\n\n'
        )
    return text
