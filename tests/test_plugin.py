import asyncio
import importlib.util
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from telegram import Update, User
from telegram.ext import Application, MessageHandler, filters

PROJECT = Path(__file__).resolve().parents[1]

class PluginTests(unittest.TestCase):
    def test_transport_requires_no_configured_bot_identity(self):
        spec = importlib.util.spec_from_file_location('identity_plugin', PROJECT/'__init__.py', submodule_search_locations=[str(PROJECT)])
        import sys
        plugin = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = plugin
        spec.loader.exec_module(plugin)
        factories = []
        config = {'channel_id': 42, 'owner_user_id': 42}
        ctx = SimpleNamespace(profile_name='cron', get_config=lambda key, default: config.get(key, default),
                              register_platform_handler=lambda platform, factory: factories.append(factory))
        plugin.register(ctx)
        self.assertEqual(len(factories), 1)

    def test_private_chat_reply_auth_receipt_and_dispatch(self):
        self._exercise_transport('private')

    def test_transport_queue_auth_dedupe_edit_and_unrelated_dispatch(self):
        for chat_type in ('channel', 'supergroup'):
            with self.subTest(chat_type=chat_type):
                self._exercise_transport(chat_type)

    def _exercise_transport(self, chat_type):
        spec = importlib.util.spec_from_file_location('test_unified_plugin', PROJECT/'__init__.py', submodule_search_locations=[str(PROJECT)])
        self.assertTrue(spec and spec.loader, 'plugin implementation is required')
        plugin = importlib.util.module_from_spec(spec)
        import sys
        sys.modules[spec.name] = plugin
        spec.loader.exec_module(plugin)
        from store import enqueue, claim_notification, finish_notification, reply_rows
        with tempfile.TemporaryDirectory(dir=PROJECT) as tmp:
            db = Path(tmp)/'state.sqlite3'
            item = enqueue('default', dict(category='needs_owner', source='test', source_id='one', title='test', body='original'), db)
            chat_id = 42 if chat_type == 'private' else -100100
            finish_notification(claim_notification(db), 'delivered', db, message_id=50, chat_id=str(chat_id))
            config = {'role':'transport','channel_id':chat_id,'owner_user_id':42,'db_path':str(db)}
            factories=[]
            ctx=SimpleNamespace(profile_name='cron', get_config=lambda key,default:config.get(key,default), register_platform_handler=lambda platform,factory:factories.append(factory))
            from unittest.mock import patch
            real = plugin.settings.from_context(ctx, transport=True)
            real['db_path'] = db
            with patch.object(plugin.settings, 'from_context', return_value=real):
                plugin.register(ctx)
            app=Application.builder().token('777:TEST').build()
            app.bot._bot_user=User(777,'Cron',True,username='cronbot');app._initialized=True
            for factory in factories:factory(app,None)
            calls=[]
            async def downstream(update, context):calls.append(update.update_id)
            app.add_handler(MessageHandler(filters.ALL,downstream),group=0)
            def update(i,actor=42,parent_id=50,parent_bot=777,edited=False,sender=False):
                chat={'id':chat_id,'type':chat_type,'title':'test'}
                msg={'message_id':i,'date':1,'chat':chat,'from':{'id':actor,'is_bot':False,'first_name':'Owner'},'text':' yes\n please ', 'reply_to_message':{'message_id':parent_id,'date':1,'chat':chat,'from':{'id':parent_bot,'is_bot':True,'first_name':'bot'}}}
                if sender:msg['sender_chat']=chat
                key = ('edited_channel_post' if edited else 'channel_post') if chat_type == 'channel' else ('edited_message' if edited else 'message')
                return Update.de_json({'update_id':i,key:msg},app.bot)
            async def run():
                wrong = update(57)
                object.__setattr__(wrong.effective_message.chat, 'type', 'supergroup' if chat_type == 'private' else 'private')
                await app.process_update(wrong)
                await app.process_update(update(51));await app.process_update(update(51))
                await app.process_update(update(52,actor=99));await app.process_update(update(53,sender=True))
                await app.process_update(update(54,parent_bot=999));await app.process_update(update(55,edited=True))
                await app.process_update(update(56,parent_id=100))
            asyncio.run(run())
            rows=reply_rows(db)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['notification_id'],item['id'])
            self.assertEqual(rows[0]['answer'],' yes\n please ')
            self.assertEqual(calls,[56])

if __name__=='__main__':unittest.main()
