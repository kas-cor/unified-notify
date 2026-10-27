#!/usr/bin/env python3
"""Cron-owned Telegram transport for the default-profile notification store."""
from __future__ import annotations

import fcntl
import html
import http.client
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

if __package__:
    from . import store, settings
else:
    import store, settings


class DeliveryOutcome(Exception):
    def __init__(self, status, detail, retry_after=0):
        super().__init__(detail)
        self.status = status
        self.retry_after = retry_after


def render(item, bot_username=''):
    heading = 'Плагин коммуникации'
    plain = f"{heading}\n\nПрофиль: {item['origin_profile']}\nТема: {item['title']}\n\n{item['body']}"
    if len(plain.encode('utf-16-le')) // 2 > 4096:
        raise DeliveryOutcome('failed','notification exceeds Telegram UTF-16 length limit')
    return (f"<b>{heading}</b>\n\n<b>Профиль:</b> {html.escape(item['origin_profile'])}\n"
            f"<b>Тема:</b> {html.escape(item['title'])}\n\n{html.escape(item['body'])}")


def reply_markup(item,bot_username=''):
    return None


def telegram_send_once(token, chat_id, text, *, reply_markup=None):
    conn = http.client.HTTPSConnection('api.telegram.org', timeout=15)
    try:
        try:
            conn.connect()
        except (OSError,http.client.HTTPException) as exc:
            raise DeliveryOutcome('retry','connection failed: '+type(exc).__name__) from None
        fields={'chat_id':chat_id,'text':text,'parse_mode':'HTML','disable_web_page_preview':'true'}
        if reply_markup is not None:
            fields['reply_markup']=json.dumps(reply_markup,ensure_ascii=False)
        payload=urlencode(fields).encode()
        try:
            conn.request('POST',f'/bot{token}/sendMessage',body=payload,
                         headers={'Content-Type':'application/x-www-form-urlencoded'})
            response=conn.getresponse()
            raw=response.read(65536)
        except (OSError,http.client.HTTPException) as exc:
            raise DeliveryOutcome('unknown','request outcome unconfirmed: '+type(exc).__name__) from None
        try:
            data=json.loads(raw)
        except (ValueError,UnicodeError):
            raise DeliveryOutcome('unknown','invalid Telegram response') from None
        if not isinstance(data,dict):
            raise DeliveryOutcome('unknown','unexpected Telegram response type')
        if response.status==200 and data.get('ok') is True:
            receipt=data.get('result') or {}
            message_id=receipt.get('message_id')
            actual_chat=str((receipt.get('chat') or {}).get('id',''))
            if isinstance(message_id,int) and actual_chat==str(chat_id):
                return message_id,actual_chat
            raise DeliveryOutcome('unknown','receipt has no matching message ID and chat')
        if data.get('ok') is False:
            code=data.get('error_code',response.status)
            status='retry' if code==429 or (isinstance(code,int) and code>=500) else 'failed'
            retry_after=(data.get('parameters') or {}).get('retry_after',0)
            if not isinstance(retry_after,int):
                retry_after=0
            raise DeliveryOutcome(status,f'Telegram rejected message: HTTP {response.status}',retry_after)
        raise DeliveryOutcome('unknown','Telegram acceptance unconfirmed')
    finally:
        conn.close()


def send_pending(db_path=store.DEFAULT_DB, *, token, chat_id, transport=telegram_send_once, limit=10, spacing_seconds=1, bot_username=''):
    if not token or not chat_id:
        raise ValueError('Telegram credentials and destination required')
    result={key:0 for key in ('claimed','delivered','retry','unknown','failed')}
    for index in range(max(0,min(int(limit),10))):
        item=store.claim_notification(db_path)
        if item is None:
            break
        result['claimed']+=1
        try:
            markup=reply_markup(item,bot_username)
            if markup:
                message_id,actual_chat=transport(token,str(chat_id),render(item,bot_username),reply_markup=markup)
            else:
                message_id,actual_chat=transport(token,str(chat_id),render(item,bot_username))
        except DeliveryOutcome as outcome:
            saved=store.finish_notification(item,outcome.status,db_path,error=str(outcome),retry_after=outcome.retry_after)
            result[outcome.status if saved else 'unknown']+=1
        except Exception as exc:
            store.finish_notification(item,'unknown',db_path,error='sender exception: '+type(exc).__name__)
            result['unknown']+=1
        else:
            saved=store.finish_notification(item,'delivered',db_path,message_id=message_id,chat_id=actual_chat)
            result['delivered' if saved else 'unknown']+=1
        if spacing_seconds and index+1<limit:
            time.sleep(spacing_seconds)
    return result


def load_bot_token(config=None):
    from hermes_cli.config import get_env_value
    config = config or settings.load()
    token = get_env_value('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ValueError('transport Telegram credential unavailable')
    return token


def main():
    from hermes_constants import get_hermes_home
    config = settings.load()
    if __package__:
        from . import onboard
    else:
        import onboard
    try:
        plan = onboard.profiles_plan(config['root_home'], onboard.config_for)
    except ValueError as exc:
        raise PermissionError('tick requires exactly one enabled installed transport plugin') from exc
    transport = next(entry for entry in plan if entry['native_plugin'])
    if Path(get_hermes_home()).resolve() != transport['home'].resolve():
        raise PermissionError('tick requires the enabled plugin profile')
    config = settings.validate(config, transport=True)
    runtime = config['root_home']/config['runtime_path']
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (runtime/'sender.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        result = send_pending(config['db_path'], token=load_bot_token(config), chat_id=config['channel_id'],
            limit=config['batch_size'], spacing_seconds=config['spacing_seconds'])
        if __package__:
            from .dispatcher import dispatch_replies
        else:
            from dispatcher import dispatch_replies
        replies = dispatch_replies(config['db_path'], limit=config['batch_size'])
        if result['claimed']:
            print(json.dumps(result), file=sys.stderr)
        if any(replies.values()):
            print('replies: '+json.dumps(replies), file=sys.stderr)
        return 1 if result['unknown'] or result['failed'] or replies['failed'] else 0


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('notification sender failed: '+type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)
