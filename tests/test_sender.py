import importlib.util
import tempfile
import unittest
from pathlib import Path

STORE = Path(__file__).resolve().parents[1]/'store.py'
SENDER = Path(__file__).resolve().parents[1]/'sender.py'

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class SenderTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SENDER.is_file(), 'unified cron sender does not exist')
        self.m = load(SENDER, 'sender_test')
        self.store = load(STORE, 'store_test')
        self.tmp = tempfile.TemporaryDirectory(dir=SENDER.parent)
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'outbox.db'
        self.item = self.store.enqueue('finance',dict(category='needs_owner',source='test',source_id='1',title='Тема <b>',body='Текст & данные'),self.db)

    def test_message_format_and_confirmed_delivery(self):
        calls=[]
        def transport(token, chat, text):
            calls.append(text)
            return 7, chat
        result=self.m.send_pending(self.db,token='fake',chat_id='-1',transport=transport,spacing_seconds=0)
        self.assertEqual(result['delivered'],1)
        self.assertIn('finance',calls[0])
        self.assertIn('Тема &lt;b&gt;',calls[0])
        self.assertIn('Текст &amp; данные',calls[0])
        self.assertNotIn('/replay',calls[0])
        self.assertTrue(calls[0].startswith('<b>Плагин коммуникации</b>\n\n'))
        self.assertNotIn('Ответьте на этот пост канала',calls[0])
        self.assertIsNone(self.m.reply_markup({'reply_mode':'dm','id':self.item['id']}))
        self.assertEqual(self.store.get_notification(self.item['id'],self.db)['status'],'delivered')
        self.assertEqual(self.m.send_pending(self.db,token='fake',chat_id='-1',transport=transport)['claimed'],0)

    def test_uncertain_delivery_is_not_retried(self):
        def transport(*args):
            raise self.m.DeliveryOutcome('unknown','timeout after sending')
        result=self.m.send_pending(self.db,token='fake',chat_id='-1',transport=transport,spacing_seconds=0)
        self.assertEqual(result['unknown'],1)
        self.assertEqual(result['delivered'],0)
        self.assertEqual(self.m.send_pending(self.db,token='fake',chat_id='-1',transport=transport)['claimed'],0)

    def test_permanent_rejection_is_not_retried(self):
        def transport(*args):
            raise self.m.DeliveryOutcome('failed','forbidden')
        result=self.m.send_pending(self.db,token='fake',chat_id='-1',transport=transport,spacing_seconds=0)
        self.assertEqual(result['failed'],1)
        self.assertEqual(self.store.get_notification(self.item['id'],self.db)['status'],'failed')

if __name__=='__main__':
    unittest.main()
