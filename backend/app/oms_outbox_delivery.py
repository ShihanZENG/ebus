"""Deliver ERP-owned Storefront order events to the standalone OMS mirror."""
import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
from sqlalchemy import and_, or_, select

from . import models as m
from .db import build_engine, sessions


def _eligible(now):
    return or_(
        and_(m.OmsOutboxEvent.status == 'pending', or_(
            m.OmsOutboxEvent.next_attempt_at.is_(None), m.OmsOutboxEvent.next_attempt_at <= now)),
        and_(m.OmsOutboxEvent.status == 'processing', m.OmsOutboxEvent.next_attempt_at <= now),
    )


def deliver_once(session_factory, transport, oms_url: str, secret: str, now: datetime | None = None):
    """Claim one event; a lost acknowledgment is safe because OMS deduplicates by key."""
    if not secret or not oms_url:
        raise ValueError('OMS bridge URL and secret must be configured')
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    with session_factory() as db:
        event = db.scalar(select(m.OmsOutboxEvent).where(_eligible(now))
            .order_by(m.OmsOutboxEvent.created_at, m.OmsOutboxEvent.id)
            .with_for_update(skip_locked=True).limit(1))
        if event is None:
            return None
        event.status = 'processing'
        event.attempt_count += 1
        event.next_attempt_at = now + timedelta(minutes=2)
        event_id, attempt = event.id, event.attempt_count
        body = {'event_id': event.id, 'idempotency_key': event.idempotency_key,
                'contract_version': event.contract_version, 'event_type': event.event_type,
                'payload': event.payload}
        db.commit()
    try:
        response = transport.post(oms_url.rstrip('/') + '/internal/erp-order-mirrors',
            json=body, headers={'X-OMS-Bridge-Secret': secret}, timeout=10)
        response.raise_for_status()
        acknowledgment = response.json()
        if (acknowledgment.get('event_id') != body['event_id'] or
                acknowledgment.get('idempotency_key') != body['idempotency_key'] or
                acknowledgment.get('erp_order_id') != body['payload']['order_id'] or
                not acknowledgment.get('mirror_id')):
            raise ValueError('OMS acknowledgment does not match ERP event')
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        with session_factory() as db:
            event = db.get(m.OmsOutboxEvent, event_id)
            if event.status != 'processing' or event.attempt_count != attempt:
                return {'event_id': event_id, 'status': 'superseded'}
            event.status = 'pending'
            event.next_attempt_at = now + timedelta(seconds=min(3600, 5 * 2 ** min(attempt, 10)))
            event.last_error = f'{type(exc).__name__}: {str(exc)}'[:500]
            db.commit()
        return {'event_id': event_id, 'status': 'pending', 'attempt_count': attempt}
    with session_factory() as db:
        event = db.get(m.OmsOutboxEvent, event_id)
        if event.status != 'processing' or event.attempt_count != attempt:
            return {'event_id': event_id, 'status': 'superseded'}
        event.status = 'delivered'
        event.delivered_at = now
        event.next_attempt_at = None
        event.last_error = ''
        db.commit()
    return {'event_id': event_id, 'status': 'delivered', 'attempt_count': attempt,
            'mirror_id': acknowledgment['mirror_id']}


def _configuration():
    url, secret = os.getenv('OMS_BRIDGE_URL', ''), os.getenv('OMS_BRIDGE_SECRET', '')
    parsed = urlsplit(url)
    if not url or not secret or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError('Set OMS_BRIDGE_URL and OMS_BRIDGE_SECRET without URL credentials')
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('OMS_BRIDGE_URL must be an HTTP(S) origin')
    if parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('Plain HTTP OMS bridge is limited to loopback')
    if parsed.path not in ('', '/'):
        raise ValueError('OMS_BRIDGE_URL must be an origin without a path')
    return url.rstrip('/'), secret


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--once', action='store_true')
    mode.add_argument('--loop', action='store_true')
    args = parser.parse_args()
    url, secret = _configuration()
    engine = build_engine()
    try:
        with httpx.Client() as transport:
            while True:
                result = deliver_once(sessions(engine), transport, url, secret)
                if result is not None:
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                if args.once:
                    return
                if result is None:
                    time.sleep(10)
                elif result['status'] != 'delivered':
                    time.sleep(5)
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
