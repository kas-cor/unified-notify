"""Native Hermes unified notifications: Telegram transport."""
from __future__ import annotations
import asyncio
import logging

from . import settings

logger = logging.getLogger(__name__)


def register(ctx):
    config = settings.from_context(ctx, transport=True)

    def unified_channel_factory(native, adapter):
        from telegram.ext import ApplicationHandlerStop, MessageHandler, filters

        async def handle(update, context):
            message = (getattr(update, 'channel_post', None) or getattr(update, 'edited_channel_post', None)
                       or getattr(update, 'message', None) or getattr(update, 'edited_message', None))
            if message is None or message.chat.id != config['channel_id']:
                return
            if ((config['channel_id'] > 0 and message.chat.type != 'private')
                    or (config['channel_id'] < 0 and message.chat.type not in ('channel', 'group', 'supergroup'))):
                raise ApplicationHandlerStop
            parent = getattr(message, 'reply_to_message', None)
            external = getattr(message, 'external_reply', None)
            if parent is None and external is None:
                return
            try:
                own_id = native.bot.id
            except (AttributeError, RuntimeError):
                raise ApplicationHandlerStop
            author = getattr(parent, 'from_user', None)
            if (external is not None or author is None or author.id != own_id
                    or getattr(getattr(parent, 'chat', None), 'id', None) != config['channel_id']):
                raise ApplicationHandlerStop

            try:
                from . import store
                notification = await asyncio.to_thread(store.notification_for_channel_post,
                    config['channel_id'], parent.message_id, config['db_path'])
            except Exception:
                logger.warning('Notification receipt lookup failed; update blocked')
                raise ApplicationHandlerStop
            if notification is None:
                return
            try:
                # Edited publications never change or re-deliver an admitted answer.
                if getattr(update, 'channel_post', None) is None and getattr(update, 'message', None) is None:
                    return
                actor = getattr(message, 'from_user', None)
                text = getattr(message, 'text', None)
                if (actor is None or actor.id != config['owner_user_id'] or actor.is_bot is not False
                        or getattr(message, 'sender_chat', None) is not None
                        or not isinstance(text, str) or not text.strip() or len(text) > 8000
                        or text.startswith('/') or not isinstance(message.message_id, int) or message.message_id <= 0):
                    return
                row = await asyncio.to_thread(store.receive_reply, notification['id'], text,
                    sender_id=actor.id, chat_id=message.chat.id, message_id=message.message_id,
                    allowed_user_id=config['owner_user_id'], allowed_chat_id=config['channel_id'],
                    notification_chat_id=config['channel_id'], db_path=config['db_path'])
                logger.info('Notification reply queued id=%s origin=%s inserted=%s',
                    row['id'], row['origin_profile'], row['inserted'])
            except Exception:
                logger.warning('Notification reply admission failed; update blocked')
            finally:
                raise ApplicationHandlerStop

        channel_updates = (filters.UpdateType.CHANNEL_POST | filters.UpdateType.EDITED_CHANNEL_POST
                           | filters.UpdateType.MESSAGE | filters.UpdateType.EDITED_MESSAGE)
        native.add_handler(MessageHandler(filters.Chat(chat_id=config['channel_id']) & channel_updates,
            handle, block=True), group=-106)
        logger.info('Unified notification channel handler installed transport')

    ctx.register_platform_handler('telegram', unified_channel_factory)
