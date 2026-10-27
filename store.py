#!/usr/bin/env python3
"""Default-profile notification receiver and durable storage; no network sending."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from . import settings
else:
    import settings
_config = settings.load()
ROOT = _config['root_home']
DEFAULT_DB = _config['db_path']
ACTION_CATEGORY = _config['action_category']
DELIVERY_NAMESPACE = _config['delivery_namespace']
SCHEMA = '''
CREATE TABLE IF NOT EXISTS notifications (
 id TEXT PRIMARY KEY, dedupe_key TEXT UNIQUE NOT NULL,
 origin_profile TEXT NOT NULL, origin_session TEXT,
 category TEXT NOT NULL, source TEXT NOT NULL, source_id TEXT NOT NULL,
 title TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL,
 reply_mode TEXT NOT NULL DEFAULT 'comment',
 status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
 next_attempt_at REAL NOT NULL DEFAULT 0, lease_token TEXT, lease_until REAL,
 telegram_message_id INTEGER, telegram_chat_id TEXT, delivered_at TEXT, last_error TEXT
);
CREATE INDEX IF NOT EXISTS notifications_due ON notifications(status,next_attempt_at,created_at);
CREATE TABLE IF NOT EXISTS discussion_posts (
 group_chat_id TEXT NOT NULL, group_message_id TEXT NOT NULL,
 channel_chat_id TEXT NOT NULL, channel_message_id TEXT NOT NULL,
 PRIMARY KEY(group_chat_id,group_message_id)
);
CREATE TABLE IF NOT EXISTS replies (
 id TEXT PRIMARY KEY, telegram_event TEXT UNIQUE NOT NULL,
 notification_id TEXT NOT NULL, origin_profile TEXT NOT NULL,
 message TEXT NOT NULL, answer TEXT NOT NULL, sender_id TEXT NOT NULL,
 created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 delivery_id TEXT NOT NULL UNIQUE, next_attempt_at REAL NOT NULL DEFAULT 0,
 lease_token TEXT, lease_until REAL, delivered_at TEXT, last_error TEXT
);
CREATE TABLE IF NOT EXISTS dm_reply_context (
 user_id TEXT NOT NULL, chat_id TEXT NOT NULL, notification_id TEXT NOT NULL,
 expires_at REAL NOT NULL, PRIMARY KEY(user_id,chat_id)
);
'''


def stamp():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def database(path=DEFAULT_DB):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() and path.stat().st_mode & 0o077:
        raise PermissionError('notification database permissions must be 600')
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(fd)
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA busy_timeout=10000')
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=FULL')
        conn.executescript(SCHEMA)
        if 'reply_mode' not in {row[1] for row in conn.execute('PRAGMA table_info(notifications)')}:
            conn.execute('BEGIN IMMEDIATE')
            try:
                if 'reply_mode' not in {row[1] for row in conn.execute('PRAGMA table_info(notifications)')}:
                    conn.execute("ALTER TABLE notifications ADD COLUMN reply_mode TEXT NOT NULL DEFAULT 'comment'")
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        for suffix in ('-wal', '-shm'):
            sidecar = Path(str(path) + suffix)
            if sidecar.exists():
                sidecar.chmod(0o600)
        yield conn
    finally:
        conn.close()


def validate_profile(profile):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', profile):
        raise ValueError('invalid origin profile')
    return profile


def enqueue(profile, item, db_path=DEFAULT_DB):
    profile = validate_profile(profile)
    fields = {key: str(item.get(key, '')).strip() for key in ('category','source','source_id','title','body')}
    if fields['category'] == 'needs_owner':
        fields['category'] = ACTION_CATEGORY
    if fields['category'] not in (ACTION_CATEGORY,'important_update'):
        raise ValueError('category must be the configured action category or important_update')
    if not all(fields.values()):
        raise ValueError('category, source, source_id, title and body are required')
    if len(fields['title']) > 200 or len(fields['body']) > 3500 or len(fields['source_id']) > 512:
        raise ValueError('notification payload is too long')
    material = json.dumps([profile, fields['category'], fields['source'], fields['source_id']], ensure_ascii=False)
    key = hashlib.sha256(material.encode()).hexdigest()
    notification_id = 'n' + key[:20]
    reply_mode=item.get('reply_mode','comment')
    if reply_mode not in ('comment','dm'):
        raise ValueError('invalid reply mode')
    with database(db_path) as conn:
        cur = conn.execute('''INSERT OR IGNORE INTO notifications
          (id,dedupe_key,origin_profile,origin_session,category,source,source_id,title,body,created_at,reply_mode)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
          (notification_id,key,profile,item.get('origin_session'),fields['category'],fields['source'],
           fields['source_id'],fields['title'],fields['body'],stamp(),reply_mode))
        row = conn.execute('SELECT id,status FROM notifications WHERE dedupe_key=?', (key,)).fetchone()
        if row is None:
            raise RuntimeError('notification ID collision')
        return dict(row, inserted=cur.rowcount == 1)


def import_legacy_notification(profile, item, db_path=DEFAULT_DB):
    profile=validate_profile(profile)
    fields={key:str(item.get(key,'')).strip() for key in ('category','source','source_id','title','body')}
    if fields['category'] == 'needs_owner':
        fields['category'] = ACTION_CATEGORY
    if fields['category'] not in (ACTION_CATEGORY,'important_update') or not all(fields.values()):
        raise ValueError('invalid legacy notification')
    key=hashlib.sha256(json.dumps([profile,fields['category'],fields['source'],fields['source_id']],ensure_ascii=False).encode()).hexdigest()
    notification_id='n'+key[:20]
    status=item.get('status')
    if status not in ('pending','retry','delivered','unknown','failed'):
        status='unknown'
    if status=='delivered' and (not isinstance(item.get('telegram_message_id'),int) or not item.get('telegram_chat_id')):
        status='unknown'
    next_at=item.get('next_attempt_at')
    next_at=datetime.fromisoformat(next_at).timestamp() if isinstance(next_at,str) and next_at else 0
    with database(db_path) as conn:
        cur=conn.execute('''INSERT OR IGNORE INTO notifications
          (id,dedupe_key,origin_profile,category,source,source_id,title,body,created_at,status,attempts,
           next_attempt_at,telegram_message_id,telegram_chat_id,delivered_at,last_error)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (notification_id,key,profile,fields['category'],fields['source'],fields['source_id'],fields['title'],fields['body'],
           item.get('created_at') or stamp(),status,item.get('attempts',0),next_at,item.get('telegram_message_id'),
           str(item['telegram_chat_id']) if item.get('telegram_chat_id') else None,item.get('delivered_at'),item.get('last_error')))
        row=conn.execute('SELECT id,status FROM notifications WHERE dedupe_key=?',(key,)).fetchone()
        return dict(row,inserted=cur.rowcount==1)


def get_notification(notification_id, db_path=DEFAULT_DB):
    with database(db_path) as conn:
        row = conn.execute('SELECT * FROM notifications WHERE id=?', (notification_id,)).fetchone()
        return dict(row) if row else None


def current_profile():
    home = Path(os.environ.get('HERMES_HOME', str(ROOT)))
    if home == ROOT:
        return 'default'
    if home.parent == ROOT / 'profiles':
        return validate_profile(home.name)
    raise ValueError('cannot infer local Hermes profile from HERMES_HOME')


def claim_notification(db_path=DEFAULT_DB, *, now=None, lease_seconds=120):
    now = time.time() if now is None else now
    with database(db_path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        try:
            conn.execute("UPDATE notifications SET status='unknown',lease_token=NULL,lease_until=NULL,"
                         "last_error='send lease expired; delivery unconfirmed' WHERE status='sending' AND lease_until<?", (now,))
            row = conn.execute("SELECT * FROM notifications WHERE status IN ('pending','retry') "
                               "AND next_attempt_at<=? ORDER BY created_at,id LIMIT 1", (now,)).fetchone()
            if row is None:
                conn.commit()
                return None
            lease = uuid.uuid4().hex
            conn.execute("UPDATE notifications SET status='sending',attempts=attempts+1,lease_token=?,lease_until=? WHERE id=?",
                         (lease, now + lease_seconds, row['id']))
            conn.commit()
            return dict(row, lease_token=lease, attempts=row['attempts'] + 1)
        except BaseException:
            conn.rollback()
            raise


def finish_notification(item, status, db_path=DEFAULT_DB, *, message_id=None, chat_id=None, error=None, retry_after=0):
    if status not in ('delivered','retry','unknown','failed'):
        raise ValueError('invalid delivery status')
    if status == 'delivered' and (not isinstance(message_id,int) or not chat_id):
        raise ValueError('delivery requires Telegram receipt')
    delay = max(min(30 * 2 ** min(max(0,item['attempts'] - 1), 12), 21600), retry_after or 0)
    with database(db_path) as conn:
        cur = conn.execute('''UPDATE notifications SET status=?,telegram_message_id=?,telegram_chat_id=?,
          delivered_at=?,next_attempt_at=?,last_error=?,lease_token=NULL,lease_until=NULL
          WHERE id=? AND status='sending' AND lease_token=?''',
          (status,message_id,str(chat_id) if chat_id is not None else None,stamp() if status=='delivered' else None,
           time.time()+delay if status=='retry' else 0,error,item['id'],item['lease_token']))
        return cur.rowcount == 1


def receive_reply(notification_id, answer, *, sender_id, chat_id, message_id, allowed_user_id, allowed_chat_id, notification_chat_id=None, db_path=DEFAULT_DB):
    if not allowed_user_id or not allowed_chat_id or str(sender_id)!=str(allowed_user_id) or str(chat_id)!=str(allowed_chat_id):
        raise PermissionError('only the configured owner in the notification chat may reply')
    if not isinstance(answer, str) or not answer.strip() or len(answer)>8000 or not message_id:
        raise ValueError('reply text and Telegram message identity required')
    with database(db_path) as conn:
        notification = conn.execute("SELECT * FROM notifications WHERE id=? AND status='delivered' AND telegram_chat_id=?",
                                    (notification_id,str(notification_chat_id or allowed_chat_id))).fetchone()
        if notification is None:
            raise ValueError('delivered notification not found in this chat')
        event = f'{chat_id}:{message_id}'
        reply_id = 'r' + hashlib.sha256(event.encode()).hexdigest()[:20]
        message = (f"Ответ владельца на уведомление {notification_id}\n"
                   f"Профиль: {notification['origin_profile']}\nТема: {notification['title']}\n\n"
                   f"Источник: {notification['source']}; ID события: {notification['source_id']}\n\n"
                   f"Исходное сообщение:\n{notification['body']}\n\nОтвет владельца:\n{answer}")
        cur = conn.execute('''INSERT OR IGNORE INTO replies
          (id,telegram_event,notification_id,origin_profile,message,answer,sender_id,created_at,delivery_id)
          VALUES(?,?,?,?,?,?,?,?,?)''',
          (reply_id,event,notification_id,notification['origin_profile'],message,answer,str(sender_id),stamp(),
           hashlib.sha256((DELIVERY_NAMESPACE+':'+reply_id).encode()).hexdigest()))
        row = conn.execute('SELECT * FROM replies WHERE telegram_event=?',(event,)).fetchone()
        if row['notification_id'] != notification_id or row['answer'] != answer:
            raise ValueError('Telegram event already belongs to another reply')
        return dict(row,inserted=cur.rowcount==1)


def _check_dm_actor(user_id,chat_id,allowed_user_id):
    if not allowed_user_id or str(user_id)!=str(allowed_user_id) or str(chat_id)!=str(allowed_user_id):
        raise PermissionError('notification DM requires the owner in a private chat')


def begin_dm_reply(notification_id,*,user_id,chat_id,allowed_user_id,notification_chat_id,db_path=DEFAULT_DB):
    _check_dm_actor(user_id,chat_id,allowed_user_id)
    with database(db_path) as conn:
        notification=conn.execute("SELECT * FROM notifications WHERE id=? AND status='delivered' AND telegram_chat_id=?",
                                  (notification_id,str(notification_chat_id))).fetchone()
        if notification is None:
            raise ValueError('delivered notification not found')
        conn.execute('''INSERT INTO dm_reply_context VALUES(?,?,?,?) ON CONFLICT(user_id,chat_id)
          DO UPDATE SET notification_id=excluded.notification_id,expires_at=excluded.expires_at''',
          (str(user_id),str(chat_id),notification_id,time.time()+3600))
        return dict(notification)


def get_dm_context(user_id,chat_id,db_path=DEFAULT_DB):
    with database(db_path) as conn:
        row=conn.execute('SELECT * FROM dm_reply_context WHERE user_id=? AND chat_id=? AND expires_at>?',
                         (str(user_id),str(chat_id),time.time())).fetchone()
        return dict(row) if row else None


def receive_dm_reply(answer,*,user_id,chat_id,message_id,allowed_user_id,notification_chat_id,db_path=DEFAULT_DB):
    _check_dm_actor(user_id,chat_id,allowed_user_id)
    answer=answer.strip()
    if not answer or len(answer)>8000 or not message_id:
        raise ValueError('reply text and message identity required')
    with database(db_path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        try:
            event=f'{chat_id}:{message_id}'
            existing=conn.execute('SELECT * FROM replies WHERE telegram_event=?',(event,)).fetchone()
            if existing is not None:
                if existing['answer']!=answer or existing['sender_id']!=str(user_id):
                    raise ValueError('Telegram event conflict')
                conn.commit()
                return dict(existing,inserted=False)
            notification=conn.execute('''SELECT n.* FROM dm_reply_context d JOIN notifications n ON n.id=d.notification_id
              WHERE d.user_id=? AND d.chat_id=? AND d.expires_at>? AND n.status='delivered' AND n.telegram_chat_id=?''',
              (str(user_id),str(chat_id),time.time(),str(notification_chat_id))).fetchone()
            if notification is None:
                raise ValueError('no active notification reply context')
            reply_id='r'+hashlib.sha256(event.encode()).hexdigest()[:20]
            message=(f"Ответ владельца на уведомление {notification['id']}\n"
                     f"Профиль: {notification['origin_profile']}\nТема: {notification['title']}\n\n"
                     f"Источник: {notification['source']}; ID события: {notification['source_id']}\n\n"
                     f"Исходное сообщение:\n{notification['body']}\n\nОтвет владельца:\n{answer}")
            conn.execute('''INSERT INTO replies
              (id,telegram_event,notification_id,origin_profile,message,answer,sender_id,created_at,delivery_id)
              VALUES(?,?,?,?,?,?,?,?,?)''',
              (reply_id,event,notification['id'],notification['origin_profile'],message,answer,str(user_id),stamp(),
               hashlib.sha256((DELIVERY_NAMESPACE+':'+reply_id).encode()).hexdigest()))
            conn.execute('DELETE FROM dm_reply_context WHERE user_id=? AND chat_id=?',(str(user_id),str(chat_id)))
            row=conn.execute('SELECT * FROM replies WHERE id=?',(reply_id,)).fetchone()
            conn.commit()
            return dict(row,inserted=True)
        except BaseException:
            conn.rollback()
            raise


def record_discussion_post(group_chat_id,group_message_id,channel_chat_id,channel_message_id,db_path=DEFAULT_DB):
    values=tuple(map(str,(group_chat_id,group_message_id,channel_chat_id,channel_message_id)))
    if not all(values):
        raise ValueError('discussion and channel message identities required')
    with database(db_path) as conn:
        conn.execute('INSERT OR IGNORE INTO discussion_posts VALUES(?,?,?,?)',values)
        row=conn.execute('SELECT channel_chat_id,channel_message_id FROM discussion_posts WHERE group_chat_id=? AND group_message_id=?',values[:2]).fetchone()
        if tuple(row)!=values[2:]:
            raise ValueError('discussion anchor already belongs to another channel post')


def notification_for_comment(group_chat_id,anchor_message_id,db_path=DEFAULT_DB):
    with database(db_path) as conn:
        row=conn.execute('''SELECT n.* FROM notifications n JOIN discussion_posts p
          ON n.telegram_chat_id=p.channel_chat_id AND CAST(n.telegram_message_id AS TEXT)=p.channel_message_id
          WHERE p.group_chat_id=? AND p.group_message_id=? AND n.status='delivered' ''',
          (str(group_chat_id),str(anchor_message_id))).fetchone()
        return dict(row) if row else None


def notification_for_channel_post(chat_id, message_id, db_path=DEFAULT_DB):
    """Resolve only a unique, positively delivered Telegram receipt."""
    with database(db_path) as conn:
        rows = conn.execute("SELECT * FROM notifications WHERE status='delivered' AND telegram_chat_id=? AND telegram_message_id=? LIMIT 2",
                            (str(chat_id), message_id)).fetchall()
        return dict(rows[0]) if len(rows) == 1 else None


def reply_rows(db_path=DEFAULT_DB, statuses=None):
    with database(db_path) as conn:
        if statuses:
            sql='SELECT * FROM replies WHERE status IN ('+','.join('?' for _ in statuses)+') ORDER BY created_at'
            rows=conn.execute(sql,tuple(statuses)).fetchall()
        else:
            rows=conn.execute('SELECT * FROM replies ORDER BY created_at').fetchall()
        return [dict(row) for row in rows]


def claim_reply(db_path=DEFAULT_DB, *, now=None, lease_seconds=120):
    now=time.time() if now is None else now
    with database(db_path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        try:
            conn.execute("UPDATE replies SET status='unknown',lease_token=NULL,lease_until=NULL,"
                         "last_error='dispatch interrupted; reconcile exact receipt' WHERE status='dispatching' AND lease_until<?",(now,))
            row=conn.execute("SELECT * FROM replies WHERE status='pending' AND next_attempt_at<=? ORDER BY created_at LIMIT 1",(now,)).fetchone()
            if row is None:
                conn.commit()
                return None
            lease=uuid.uuid4().hex
            conn.execute("UPDATE replies SET status='dispatching',lease_token=?,lease_until=? WHERE id=?",(lease,now+lease_seconds,row['id']))
            conn.commit()
            return dict(row,lease_token=lease)
        except BaseException:
            conn.rollback()
            raise


def finish_reply(item,status,db_path=DEFAULT_DB,*,error=None):
    if status not in ('accepted','delivered','failed','pending','unknown'):
        raise ValueError('invalid reply delivery status')
    with database(db_path) as conn:
        cur=conn.execute('''UPDATE replies SET status=?,last_error=?,lease_token=NULL,lease_until=NULL,
          next_attempt_at=?,delivered_at=? WHERE id=? AND status='dispatching' AND lease_token=?''',
          (status,error,time.time()+60 if status=='pending' else 0,stamp() if status=='delivered' else None,item['id'],item['lease_token']))
        return cur.rowcount==1


def reconcile_reply(reply_id,status,db_path=DEFAULT_DB):
    if status not in ('accepted','delivered','failed','unknown'):
        raise ValueError('invalid reply receipt status')
    with database(db_path) as conn:
        cur=conn.execute("UPDATE replies SET status=?,delivered_at=? WHERE id=? AND status IN ('accepted','unknown')",
                         (status,stamp() if status=='delivered' else None,reply_id))
        return cur.rowcount==1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)

    sub = parser.add_subparsers(dest='command', required=True)
    add = sub.add_parser('enqueue')
    add.add_argument('--stdin', action='store_true', required=True)
    show = sub.add_parser('status')
    show.add_argument('id', nargs='?')
    args = parser.parse_args(argv)
    if args.command == 'enqueue':
        payload = json.load(sys.stdin)
        items = payload if isinstance(payload,list) else [payload]
        if not 1 <= len(items) <= 20:
            raise ValueError('expected 1-20 notifications')
        profile = current_profile()
        if profile != 'default' and not (ROOT / 'profiles' / profile).is_dir():
            raise ValueError('origin profile does not exist')
        print(json.dumps([enqueue(profile,item,DEFAULT_DB) for item in items],ensure_ascii=False))
    else:
        with database(DEFAULT_DB) as conn:
            rows = conn.execute('''SELECT id,origin_profile,status,attempts,telegram_message_id,
              telegram_chat_id,created_at,delivered_at FROM notifications WHERE (? IS NULL OR id=?)
              ORDER BY created_at DESC LIMIT 100''', (args.id,args.id)).fetchall()
            print(json.dumps([dict(row) for row in rows],ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('notification receiver failed: ' + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
