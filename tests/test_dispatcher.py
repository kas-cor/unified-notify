import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/'dispatcher.py'
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    assert spec is not None and spec.loader is not None
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class ReplyDispatchTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.exists(),'reply dispatcher missing')
        self.m=load(MODULE,'reply_dispatch_test')
        self.store=load(ROOT/'store.py','store_dispatch_test')
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(self.tmp.cleanup)
        self.m.ROOT=Path(self.tmp.name)
        (self.m.ROOT/'profiles/finance').mkdir(parents=True)
        self.db=Path(self.tmp.name)/'notify.db'
        n=self.store.enqueue('finance',dict(category='needs_owner',source='test',source_id='1',title='Вопрос',body='Исходный текст'),self.db)
        item=self.store.claim_notification(self.db)
        self.store.finish_notification(item,'delivered',self.db,message_id=1,chat_id='-1')
        self.reply=self.store.receive_reply(n['id'],'Разрешаю',sender_id='42',chat_id='-1',message_id='2',allowed_user_id='42',allowed_chat_id='-1',db_path=self.db)

    def test_admission_then_settlement_without_second_send(self):
        class Transport:
            def __init__(self):self.receipt=None;self.calls=[]
            def read(self,home,id):return self.receipt
            def owner(self,home):return {'profile_home':str(home)}
            def send(self,home,owner,message,id):
                self.calls.append((str(home),message,id));self.receipt={'delivery_id':id,'message':message,'status':'queued','profile_home':str(home)};return self.receipt
        t=Transport()
        result=self.m.dispatch_replies(self.db,transport=t)
        self.assertEqual(result['accepted'],1)
        self.assertEqual(self.store.reply_rows(self.db)[0]['status'],'accepted')
        self.assertIn('Исходный текст',t.calls[0][1]);self.assertIn('Разрешаю',t.calls[0][1])
        self.assertTrue(t.calls[0][0].endswith('/profiles/finance'))
        assert t.receipt is not None
        t.receipt['status']='settled'
        self.m.dispatch_replies(self.db,transport=t)
        self.assertEqual(self.store.reply_rows(self.db)[0]['status'],'delivered')
        self.assertEqual(len(t.calls),1)

    def test_lost_ack_is_held_not_resent(self):
        class Transport:
            def __init__(self):self.calls=0
            def read(self,home,id):return None
            def owner(self,home):return {'profile_home':str(home)}
            def send(self,*args):self.calls+=1;raise TimeoutError('ack lost')
        t=Transport();self.m.dispatch_replies(self.db,transport=t);self.m.dispatch_replies(self.db,transport=t)
        self.assertEqual(self.store.reply_rows(self.db)[0]['status'],'unknown')
        self.assertEqual(t.calls,1)

    def test_owner_unavailable_keeps_pending(self):
        class Transport:
            def read(self,*args):return None
            def owner(self,*args):return None
            def send(self,*args):raise AssertionError('must not send')
        self.m.dispatch_replies(self.db,transport=Transport())
        self.assertEqual(self.store.reply_rows(self.db)[0]['status'],'pending')

if __name__=='__main__':unittest.main()
