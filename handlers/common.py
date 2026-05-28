import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from filters.filters import IsPrivateChat
from keyboards.keyboards import kb_butt_quiz
from lexicon import LexiconRu
from utils import MessageProcessor

router = Router()
router.message.filter(IsPrivateChat())
logger = logging.getLogger(__name__)


@router.callback_query(F.data == 'exit')
async def clbk_exit(
    clbk: CallbackQuery, state: FSMContext, msg_processor: MessageProcessor
) -> None:
    """Handle exit callback query.

    For exit button. Clears the current state, deletes all
    previously sent messages and sends a message with the survey.

    Args:
        clbk (CallbackQuery): The callback query object.
        state (FSMContext): The state object.
        msg_processor (MessageProcessor): The message processor object.

    Returns:
        None

    """
    logger.debug('Entry')

    if not clbk.message or not isinstance(clbk.message, Message):
        logger.error('Callback query message is None or inaccessible')
        return

    try:
        await msg_processor.deletes_messages(
            msgs_remove_kb=True, msgs_for_del=True
        )
    except Exception as err:
        logger.error(
            f'Ошибка при удалении kb {err.__class__.__name__}', exc_info=True
        )

    try:
        msg = await clbk.message.answer(
            LexiconRu.text_survey,
            reply_markup=kb_butt_quiz,
            disable_web_page_preview=True,
        )
    except Exception as err:
        logger.error(f'{err.__class__.__name__}', exc_info=True)
    else:
        await msg_processor.save_msg_id(msg, msgs_for_del=True)
    await state.set_state(state=None)
    await clbk.answer()

    logger.debug('Exit')
