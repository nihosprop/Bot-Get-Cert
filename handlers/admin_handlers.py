import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis

from filters.filters import IsAdmins
from keyboards import kb_butt_quiz
from keyboards.keyboards import kb_admin
from lexicon import LexiconRu
from states.states import FSMAdminPanel
from utils import MessageProcessor, get_username

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
    if not msg.from_user:
        logger_admin.warning(
            'Login to the admin panel failed.'
            ' Message without user info received.'
        )
        return

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

    if not clbk.message or not isinstance(clbk.message, Message):
        logger_admin.warning('Callback message is None or inaccessible')
        return

    await state.set_state(state=None)
    msg = await clbk.message.edit_text(
        f'Вы вышли из админ-панели✅\n{LexiconRu.text_survey}',
        reply_markup=kb_butt_quiz,
        disable_web_page_preview=True,
    )
    if isinstance(msg, bool):
        logger_admin.warning(
            'Message is not accessible, received `bool`, expected `Message`'
        )
        return
    await msg_processor.save_msg_id(msg, msgs_for_del=True)
    await clbk.answer()


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
