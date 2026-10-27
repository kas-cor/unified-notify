#!/usr/bin/env python3
"""Cron-owned reply delivery via Hermes canonical Bot Chat authority; no LLM fallback."""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

if __package__:
    from . import store, settings
else:
    import store, settings
ROOT = settings.load()['root_home']


class NativeTransport:
    def __init__(self):
        # Script jobs run outside the checkout; use this install's native authority client.
        checkout=str(ROOT/'hermes-agent')
        if checkout not in sys.path:
            sys.path.insert(0,checkout)
        from tools import bot_live_delivery
        self.api=bot_live_delivery
    def read(self,home,delivery_id):
        return self.api.read_delivery_result(home,delivery_id)
    def owner(self,home):
        return self.api.find_canonical_live_owner(home)
    def send(self,home,owner,message,delivery_id):
        return self.api.deliver_to_live_owner(home,owner,message,delivery_id=delivery_id,notification_category='result')
    def is_predial(self,exc):
        return isinstance(exc,self.api.PreDialError)


def destination(profile):
    store.validate_profile(profile)
    home=ROOT if profile=='default' else ROOT/'profiles'/profile
    if not home.is_dir():
        raise ValueError('origin profile no longer exists')
    return home


def receipt_status(row,home,receipt):
    if not isinstance(receipt,dict):
        return 'unknown'
    if (receipt.get('delivery_id') or receipt.get('id'))!=row['delivery_id']:
        return 'unknown'
    if receipt.get('message')!=row['message']:
        return 'unknown'
    receipt_home=receipt.get('profile_home') or (receipt.get('owner') or {}).get('profile_home')
    if receipt_home and Path(receipt_home).resolve()!=home.resolve():
        return 'unknown'
    return {'queued':'accepted','claimed':'accepted','settled':'delivered',
            'failed':'failed','cancelled':'failed','ambiguous':'unknown'}.get(receipt.get('status'),'unknown')


def dispatch_replies(db_path=store.DEFAULT_DB,*,transport=None,limit=10):
    transport=transport or NativeTransport()
    result={key:0 for key in ('accepted','delivered','failed','unknown','pending')}
    # Read exact existing receipts first. An uncertain send is never automatically re-admitted.
    for row in store.reply_rows(db_path,('accepted','unknown'))[:100]:
        try:
            home=destination(row['origin_profile'])
            receipt=transport.read(home,row['delivery_id'])
            if receipt is not None:
                status=receipt_status(row,home,receipt)
                store.reconcile_reply(row['id'],status,db_path)
                result[status]+=1
        except Exception:
            continue
    for _ in range(max(0,min(limit,10))):
        row=store.claim_reply(db_path)
        if row is None:
            break
        try:
            home=destination(row['origin_profile'])
            receipt=transport.read(home,row['delivery_id'])
            if receipt is not None:
                status=receipt_status(row,home,receipt)
                store.finish_reply(row,status,db_path)
                result[status]+=1
                continue
            owner=transport.owner(home)
            if owner is None:
                raise ConnectionError('authority not ready')
        except Exception as exc:
            store.finish_reply(row,'pending',db_path,error='pre-dispatch: '+type(exc).__name__)
            result['pending']+=1
            continue
        try:
            receipt=transport.send(home,owner,row['message'],row['delivery_id'])
        except Exception as exc:
            # Only the native transport's explicit pre-dial refusal proves non-admission.
            if getattr(transport,'is_predial',lambda e:False)(exc):
                status='pending'
            else:
                try:
                    receipt=transport.read(home,row['delivery_id'])
                except Exception:
                    receipt=None
                status=receipt_status(row,home,receipt) if receipt is not None else 'unknown'
            store.finish_reply(row,status,db_path,error='dispatch: '+type(exc).__name__)
        else:
            status=receipt_status(row,home,receipt)
            store.finish_reply(row,status,db_path)
        result[status]+=1
    return result
