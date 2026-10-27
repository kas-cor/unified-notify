"""Compatibility contract; fixtures never open the operational database."""
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = importlib.import_module('store')
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'test.sqlite3'
        self.payload = dict(category='needs_owner', source='test', source_id='one', title='Тема', body='Текст')

    def test_exact_legacy_schema_ids_and_dedupe(self):
        s = self.store
        row = s.enqueue('default', self.payload, self.db)
        key = hashlib.sha256(json.dumps(['default',s.ACTION_CATEGORY,'test','one'], ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(row['id'], 'n'+key[:20])
        self.assertFalse(s.enqueue('default', dict(self.payload, body='changed'), self.db)['inserted'])
        self.assertEqual(s.get_notification(row['id'], self.db)['body'], 'Текст')
        with s.database(self.db) as conn:
            self.assertEqual([r[1] for r in conn.execute('pragma table_info(notifications)')], ['id','dedupe_key','origin_profile','origin_session','category','source','source_id','title','body','created_at','reply_mode','status','attempts','next_attempt_at','lease_token','lease_until','telegram_message_id','telegram_chat_id','delivered_at','last_error'])
            self.assertEqual({r[0] for r in conn.execute("select name from sqlite_master where type='table'")}, {'notifications','replies','discussion_posts','dm_reply_context'})
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)

    def test_expired_send_and_dispatch_never_replay(self):
        s = self.store
        n = s.enqueue('default', self.payload, self.db)
        lease = s.claim_notification(self.db, now=100, lease_seconds=10)
        self.assertIsNone(s.claim_notification(self.db, now=111))
        self.assertEqual(s.get_notification(n['id'], self.db)['status'], 'unknown')
        self.assertFalse(s.finish_notification(lease,'delivered',self.db,message_id=1,chat_id='-1'))

    def test_reply_identity_receipt_and_event_conflict(self):
        s = self.store
        n = s.enqueue('default', self.payload, self.db)
        s.finish_notification(s.claim_notification(self.db),'delivered',self.db,message_id=1,chat_id='-1')
        kw = dict(sender_id=42, chat_id=-1, message_id=8, allowed_user_id=42, allowed_chat_id=-1, db_path=self.db)
        r = s.receive_reply(n['id'],'yes',**kw)
        self.assertFalse(s.receive_reply(n['id'],'yes',**kw)['inserted'])
        expected = 'r'+hashlib.sha256(b'-1:8').hexdigest()[:20]
        self.assertEqual(r['id'],expected)
        self.assertEqual(r['delivery_id'],hashlib.sha256((s.DELIVERY_NAMESPACE+':'+expected).encode()).hexdigest())
        with self.assertRaises(ValueError): s.receive_reply(n['id'],'edited',**kw)
        with self.assertRaises(PermissionError): s.receive_reply(n['id'],'yes',**dict(kw,sender_id=99))
        s.claim_reply(self.db,now=100,lease_seconds=10)
        self.assertIsNone(s.claim_reply(self.db,now=111))
        self.assertEqual(s.reply_rows(self.db)[0]['status'],'unknown')
        self.assertEqual(s.notification_for_channel_post(-1,1,self.db)['id'],n['id'])
        s.enqueue('other',self.payload,self.db)
        s.finish_notification(s.claim_notification(self.db),'delivered',self.db,message_id=1,chat_id='-1')
        self.assertIsNone(s.notification_for_channel_post(-1,1,self.db))
