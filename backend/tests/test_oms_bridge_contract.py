"""One real Storefront checkout reaches an isolated OMS read model once."""
import importlib
import sys
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from test_erp import setup
from test_storefront import storefront, checkout
from app import models as erp_models
from app.db import sessions
from app.oms_outbox_delivery import deliver_once


def test_lost_ack_retries_into_one_oms_mirror(storefront, monkeypatch):
    erp_client, _, erp_engine, _, _, _, product = storefront
    response, _ = checkout(erp_client, product)
    assert response.status_code == 201, response.text
    with sessions(erp_engine)() as db:
        event = db.scalar(select(erp_models.OmsOutboxEvent))
        erp_order_id, source_no = event.order_id, event.payload['source_order_no']

    repo = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(repo))
    oms_models = importlib.import_module('oms.backend.app.models')
    oms_mirror = importlib.import_module('oms.backend.app.order_mirror')
    oms_security = importlib.import_module('oms.backend.app.security')
    monkeypatch.setenv('OMS_BRIDGE_SECRET', 'isolated-bridge-secret')
    oms_engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
        poolclass=StaticPool)
    oms_models.Base.metadata.create_all(oms_engine)
    oms_sessions = sessionmaker(oms_engine, expire_on_commit=False)
    oms_app = FastAPI()
    oms_app.include_router(oms_mirror.router)
    def oms_db():
        with oms_sessions() as db:
            yield db
    oms_app.dependency_overrides[oms_security.session_db] = oms_db
    attempts = []
    with TestClient(oms_app) as oms_client:
        def relay(request):
            attempts.append(request)
            accepted = oms_client.post(request.url.path, content=request.content,
                headers={'Content-Type': 'application/json', 'X-OMS-Bridge-Secret': request.headers['X-OMS-Bridge-Secret']})
            assert accepted.status_code == 200, accepted.text
            if len(attempts) == 1:
                return httpx.Response(503)  # OMS committed, acknowledgment was lost.
            return httpx.Response(200, json=accepted.json())
        with httpx.Client(transport=httpx.MockTransport(relay)) as transport:
            now = datetime(2026, 10, 31)
            first = deliver_once(sessions(erp_engine), transport, 'http://127.0.0.1:18090', 'isolated-bridge-secret', now)
            assert first['status'] == 'pending'
            second = deliver_once(sessions(erp_engine), transport, 'http://127.0.0.1:18090', 'isolated-bridge-secret', now + timedelta(hours=1))
            assert second['status'] == 'delivered'
    assert len(attempts) == 2
    with oms_sessions() as db:
        mirror = db.scalar(select(oms_models.ErpOrderMirror))
        assert db.scalar(select(func.count()).select_from(oms_models.ErpOrderMirror)) == 1
        assert mirror.erp_order_id == erp_order_id
        assert mirror.source_order_no == source_no
    with sessions(erp_engine)() as db:
        assert db.scalar(select(erp_models.OmsOutboxEvent)).status == 'delivered'
    oms_engine.dispose()
