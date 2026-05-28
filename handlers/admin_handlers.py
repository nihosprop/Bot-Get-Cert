import logging

from typing import Any

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from arq.connections import RedisSettings
from redis.asyncio import Redis

from config_data.config import Config
from filters.filters import IsAdmins
from keyboards import kb_back_cancel, kb_butt_quiz, kb_done_newsletter
from keyboards.keyboards import kb_admin
from lexicon import LexiconRu
from queues.que_utils import mass_mailing
from states.states import FSMAdminPanel
from utils import MessageProcessor, get_data_users, get_username

admin_router = Router()
admin_router.message.filter(IsAdmins())
admin_router.callback_query.filter(IsAdmins())
logger_admin = logging.getLogger(__name__)


@admin_router.message(F.text == '/start')
async def cmd_start(
    msg: Message, state: FSMContext, msg_processor: MessageProcessor
) -> None:
    logger_admin.info(f'cmd_start:{await get_username(msg)}')

    await msg_processor.deletes_messages(msgs_for_del=True)
    await state.clear()
    value = await msg.answer(
        LexiconRu.text_survey,
        reply_markup=kb_butt_quiz,
        disable_web_page_preview=True,
    )
    await msg_processor.save_msg_id(value, msgs_for_del=True)


@admin_router.callback_query(
    F.data == 'back', StateFilter(FSMAdminPanel.fill_newsletter)
)
async def clbk_back_newsletter(
    clbk: CallbackQuery, state: FSMContext, redis_data: Redis
) -> None:

    logger_admin.debug('Entry')

    if not clbk.message or not isinstance(clbk.message, Message):
        logger_admin.error('Callback message is None or inaccessible')
        return

    end_cert = str(await redis_data.get('end_number')).zfill(6)

    await clbk.message.edit_text(
        LexiconRu.text_adm_panel.format(end_cert=end_cert),
        reply_markup=kb_admin,
    )
    await state.set_state(FSMAdminPanel.admin_menu)
    await clbk.answer()

    logger_admin.debug('Exit')


@admin_router.message(F.text == '/admin')
async def cmd_admin(
    msg: Message,
    state: FSMContext,
    redis_data: Redis,
    msg_processor: MessageProcessor,
) -> None:
    logger_admin.info(
        f'Login to the admin panel:{msg.from_user.id}:'
        f'{await get_username(msg)}'
    )
    keys = set(filter(lambda _id: _id.isdigit(), await redis_data.keys()))
    logger_admin.debug(f'{keys=}')

    await msg_processor.deletes_messages(msgs_for_del=True)
    await msg.delete()
    end_cert = str(await redis_data.get('end_number')).zfill(6)

    value = await msg.answer(
        LexiconRu.text_adm_panel.format(end_cert=end_cert),
        reply_markup=kb_admin,
    )
    await msg_processor.save_msg_id(value, msgs_for_del=True)
    await state.set_state(FSMAdminPanel.admin_menu)


@admin_router.callback_query(F.data == 'exit')
async def cmd_exit(
    clbk: CallbackQuery, state: FSMContext, msg_processor: MessageProcessor
) -> None:
    logger_admin.info(
        f'Выход из админки:{clbk.from_user.id}:{await get_username(clbk)}'
    )
    await state.set_state(state=None)
    value = await clbk.message.edit_text(
        f'Вы вышли из админ-панели✅\n{LexiconRu.text_survey}',
        reply_markup=kb_butt_quiz,
        disable_web_page_preview=True,
    )
    await msg_processor.save_msg_id(value, msgs_for_del=True)
    await clbk.answer()


@admin_router.callback_query(
    F.data == 'certs_data', StateFilter(FSMAdminPanel.admin_menu)
)
async def clbk_check_data_certs(
    clbk: CallbackQuery, state: FSMContext, redis_data: Redis
) -> None:
    logger_admin.info(
        f'Запрос данных по сертификатам:'
        f'{clbk.from_user.id}:{await get_username(clbk)}'
    )
    await clbk.answer('Сбор данных…')
    text = await get_data_users(clbk, redis_data=redis_data)
    await clbk.message.edit_text(text=text)
    await state.clear()


@admin_router.callback_query(
    F.data == 'add_admin', StateFilter(FSMAdminPanel.admin_menu)
)
async def clbk_add_admin(clbk: CallbackQuery) -> None:
    await clbk.answer('Копка в разработке', show_alert=True)


@admin_router.callback_query(
    F.data == 'make_cert', StateFilter(FSMAdminPanel.admin_menu)
)
async def clbk_make_cert(clbk: CallbackQuery) -> None:
    await clbk.answer('Копка в разработке', show_alert=True)


# TODO: delete everything for newsletter
@admin_router.callback_query(
    F.data == 'newsletter', StateFilter(FSMAdminPanel.admin_menu)
)
async def clbk_newsletter(
    clbk: CallbackQuery, state: FSMContext, msg_processor: MessageProcessor
) -> None:
    # await clbk.answer(f'Кнопка в разработке', show_alert=True)
    value = await clbk.message.edit_text(
        '1. Отправить боту сообщение для рассылки.\n\n'
        '2. Подтвердить на следующем шаге!',
        reply_markup=kb_back_cancel,
    )
    await msg_processor.save_msg_id(value, msgs_for_del=True)
    await state.set_state(FSMAdminPanel.fill_newsletter)
    await clbk.answer()


@admin_router.message(StateFilter(FSMAdminPanel.fill_newsletter))
async def msg_for_newsletter(
    msg: Message, state: FSMContext, msg_processor: MessageProcessor
) -> None:
    logger_admin.debug('Entry')

    await msg_processor.deletes_messages(msgs_for_del=True)
    msg_letter = msg.text
    await state.update_data(msg_letter=msg_letter)
    value = await msg.answer(
        'Проверьте сообщение.\n\n'
        'Подтвердите или отмените рассылку.\n'
        'После завершения придет инфо-сообщение о количестве'
        ' доставок.',
        reply_markup=kb_done_newsletter,
    )
    await state.update_data({'msg_del_on_key': str(value.message_id)})
    await state.set_state(FSMAdminPanel.fill_confirm_newsletter)

    logger_admin.debug('Exit')


@admin_router.callback_query(
    F.data == 'done', StateFilter(FSMAdminPanel.fill_confirm_newsletter)
)
async def clbk_done_newsletter(
    clbk: CallbackQuery,
    redis_data: Redis,
    redis_que: RedisSettings,
    state: FSMContext,
    msg_processor: MessageProcessor,
    config: Config,
) -> None:
    logger_admin.debug('Entry')

    await msg_processor.delete_message()

    msg_letter: Any | None = await state.get_value('msg_letter')
    user_ids = set(
        map(int, filter(lambda _id: _id.isdigit(), await redis_data.keys()))
    )
    end_cert = str(await redis_data.get('end_number')).zfill(6)
    admin_ids: str = config.tg_bot.id_admins
    try:
        await mass_mailing(
            redis_que=redis_que,
            user_ids=user_ids,
            message=msg_letter,
            admin_ids=admin_ids,
            end_cert=end_cert,
        )
    except Exception as err:
        logger_admin.error(f'Ошибка при рассылке: {err}', exc_info=True)
    await state.set_state(FSMAdminPanel.admin_menu)
    await clbk.answer()

    logger_admin.debug('Exit')
