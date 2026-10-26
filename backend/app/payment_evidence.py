"""Private, order-scoped evidence upload and manual reconciliation for payments."""
import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models as m, schemas as s
from .config import ROOT
from .orders import get_order_or_404, money, payment_snapshot
from .security import record_audit, require, session_db


router = APIRouter(prefix='/api/v1/orders', tags=['订单收款凭据'])
MAX_EVIDENCE_SIZE = 10 * 1024 * 1024
PAYMENT_EVIDENCE_DIR = Path(os.getenv('PAYMENT_EVIDENCE_DIR', ROOT / 'data' / 'payment-evidence'))
ALLOWED_EVIDENCE = {
    '.pdf': ('application/pdf', lambda data: data.startswith(b'%PDF-')),
    '.png': ('image/png', lambda data: data.startswith(b'\x89PNG\r\n\x1a\n')),
    '.jpg': ('image/jpeg', lambda data: data.startswith(b'\xff\xd8\xff')),
    '.jpeg': ('image/jpeg', lambda data: data.startswith(b'\xff\xd8\xff')),
}


def _evidence_directory() -> Path:
    return Path(os.getenv('PAYMENT_EVIDENCE_DIR', str(ROOT / 'data' / 'payment-evidence')))


def _safe_filename(filename: str | None) -> tuple[str, str]:
    name = (filename or '').replace('\\', '/').split('/')[-1].strip()
    if not name or len(name) > 255:
        raise HTTPException(422, '凭据文件名无效')
    extension = Path(name).suffix.lower()
    if extension not in ALLOWED_EVIDENCE:
        raise HTTPException(422, '凭据仅支持 PDF、PNG、JPG 文件')
    return name, extension


def _payment_for_order(db, user, order_id: str, payment_id: str):
    get_order_or_404(db, user, order_id)
    payment = db.get(m.PaymentRecord, payment_id)
    if payment is None or payment.order_id != order_id:
        raise HTTPException(404, '付款记录不存在或不属于该订单')
    return payment


def _checked_evidence_path(payment):
    key = payment.evidence_key
    if not key or not re.fullmatch(r'[0-9a-f]{32}\.(?:pdf|png|jpg|jpeg)', key):
        raise HTTPException(404, '该付款记录没有凭据文件')
    root = _evidence_directory().resolve()
    path = (root / key).resolve()
    if payment.evidence_status != 'ready' or path.parent != root or not path.is_file():
        raise HTTPException(404, '凭据文件不存在')
    content = path.read_bytes()
    if len(content) != payment.evidence_size or hashlib.sha256(content).hexdigest() != payment.evidence_sha256:
        raise HTTPException(409, '凭据文件与登记时不一致，不能核对')
    return path


def recover_staged_evidence(session_factory):
    """Finish interrupted file/DB handoffs before serving traffic; never promotes unverified bytes."""
    root = _evidence_directory()
    root.mkdir(parents=True, exist_ok=True)
    with session_factory() as db:
        staged = db.scalars(select(m.PaymentRecord).where(
            m.PaymentRecord.record_type == 'real', m.PaymentRecord.evidence_status == 'staged')).all()
        referenced_keys = set(db.scalars(select(m.PaymentRecord.evidence_key).where(
            m.PaymentRecord.evidence_key.is_not(None))).all())
        for payment in staged:
            key = payment.evidence_key
            if not key or not re.fullmatch(r'[0-9a-f]{32}\.(?:pdf|png|jpg|jpeg)', key):
                payment.evidence_status = 'missing'
                continue
            final_path = root / key
            temp_path = root / f'.{key}.tmp'
            candidate = final_path if final_path.is_file() else temp_path
            if not candidate.is_file():
                payment.evidence_status = 'missing'
                continue
            data = candidate.read_bytes()
            if len(data) != payment.evidence_size or hashlib.sha256(data).hexdigest() != payment.evidence_sha256:
                payment.evidence_status = 'missing'
                continue
            if candidate == temp_path:
                os.replace(temp_path, final_path)
            payment.evidence_status = 'ready'
        db.commit()
        # Only remove randomized files that have no committed payment reference.
        for path in root.iterdir():
            key = path.name[1:-4] if path.name.startswith('.') and path.name.endswith('.tmp') else path.name
            if re.fullmatch(r'[0-9a-f]{32}\.(?:pdf|png|jpg|jpeg)', key) and key not in referenced_keys:
                path.unlink(missing_ok=True)
            elif path.name.startswith('.') and path.name.endswith('.tmp') and key in referenced_keys:
                path.unlink(missing_ok=True)


@router.post('/{order_id}/payments/real', status_code=201)
def add_real_payment(
    order_id: str,
    amount: Decimal = Form(...),
    fee_amount: Decimal = Form(...),
    currency_id: str = Form(..., min_length=36, max_length=36),
    method: str = Form(..., min_length=1, max_length=40),
    source: str = Form(..., min_length=1, max_length=120),
    external_transaction_id: str = Form(..., min_length=1, max_length=120),
    paid_at: datetime | None = Form(default=None),
    remark: str = Form(default='', max_length=500),
    evidence: UploadFile = File(...),
    db=Depends(session_db), user=Depends(require('payment_records:write')),
):
    order = get_order_or_404(db, user, order_id, lock=True)
    if order.status == 'cancelled':
        raise HTTPException(422, '已取消订单不能登记付款')
    currency = db.get(m.Dictionary, currency_id)
    if not currency or currency.kind != 'currency' or not currency.is_active:
        raise HTTPException(422, '付款币种不存在或已停用')
    if currency_id != order.currency_id:
        raise HTTPException(422, '付款币种必须与订单币种一致')
    if not amount.is_finite() or amount <= 0:
        raise HTTPException(422, '结算毛额必须大于0')
    if amount != money(amount) or len(amount.as_tuple().digits) > 12:
        raise HTTPException(422, '结算毛额最多支持两位小数且不能超出金额范围')
    if not fee_amount.is_finite() or fee_amount < 0 or fee_amount > amount:
        raise HTTPException(422, '手续费必须在0与结算毛额之间')
    if fee_amount != money(fee_amount) or len(fee_amount.as_tuple().digits) > 12:
        raise HTTPException(422, '手续费最多支持两位小数且不能超出金额范围')
    amount, fee_amount = money(amount), money(fee_amount)
    if not source.strip():
        raise HTTPException(422, '请填写平台结算来源编号')
    filename, extension = _safe_filename(evidence.filename)
    media_type, signature_check = ALLOWED_EVIDENCE[extension]
    if evidence.content_type != media_type:
        raise HTTPException(422, '凭据文件类型与文件扩展名不一致')
    content = evidence.file.read(MAX_EVIDENCE_SIZE + 1)
    if not content:
        raise HTTPException(422, '凭据文件不能为空')
    if len(content) > MAX_EVIDENCE_SIZE:
        raise HTTPException(413, '凭据文件不能超过10 MiB')
    if not signature_check(content):
        raise HTTPException(422, '凭据文件内容与声明格式不一致')
    evidence_hash = hashlib.sha256(content).hexdigest()
    external_transaction_id = external_transaction_id.strip()
    if not external_transaction_id:
        raise HTTPException(422, '请填写外部交易流水号')
    if external_transaction_id:
        existing = db.scalar(select(m.PaymentRecord).where(
            m.PaymentRecord.external_transaction_id == external_transaction_id))
        if existing:
            same = (existing.order_id == order.id and existing.amount == amount
                    and existing.fee_amount == fee_amount and existing.currency_id == currency_id
                    and existing.method == method.strip() and existing.source == source.strip()
                    and existing.evidence_sha256 == evidence_hash)
            if same:
                return JSONResponse(status_code=200, content=jsonable_encoder(payment_snapshot(existing)))
            raise HTTPException(409, '外部交易流水号已用于不同付款内容')
    duplicate = db.scalar(select(m.PaymentRecord.id).where(
        m.PaymentRecord.order_id == order_id, m.PaymentRecord.source == source.strip()).limit(1))
    if duplicate:
        raise HTTPException(409, '该订单已登记此结算来源编号')

    if paid_at is None:
        paid_at = datetime.now(timezone.utc).replace(tzinfo=None)
    elif paid_at.tzinfo is not None:
        paid_at = paid_at.astimezone(timezone.utc).replace(tzinfo=None)

    key = f'{uuid.uuid4().hex}{extension}'
    root = _evidence_directory()
    temp_path = root / f'.{key}.tmp'
    final_path = root / key
    try:
        root.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(content)
        payment = m.PaymentRecord(
            order_id=order.id, amount=amount, fee_amount=fee_amount, currency_id=currency_id,
            method=method.strip(), source=source.strip(), external_transaction_id=external_transaction_id,
            record_type='real',
            reconciliation_status='pending', evidence_name=filename, evidence_key=key,
            evidence_content_type=media_type, evidence_size=len(content),
            evidence_sha256=evidence_hash, evidence_status='staged', paid_at=paid_at,
            remark=remark.strip(),
        )
        db.add(payment)
        db.flush()
        result = payment_snapshot(payment)
        record_audit(db, user, 'payment_records', payment.id, 'create_pending_real',
                     after=jsonable_encoder(result))
        db.commit()
        os.replace(temp_path, final_path)
        payment.evidence_status = 'ready'
        db.commit()
        result = payment_snapshot(payment)
        return result
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        temp_path.unlink(missing_ok=True)
        raise HTTPException(409, '外部交易流水号或结算来源编号冲突')
    except Exception:
        db.rollback()
        # Keep staged files: a committed-but-unacknowledged row is recovered at next startup.
        raise HTTPException(500, '收款凭据保存失败，未登记付款')
    finally:
        evidence.file.close()


@router.get('/{order_id}/payments/{payment_id}/evidence')
def get_payment_evidence(order_id: str, payment_id: str, db=Depends(session_db),
                         user=Depends(require('payment_records:read'))):
    payment = _payment_for_order(db, user, order_id, payment_id)
    path = _checked_evidence_path(payment)
    return FileResponse(path, media_type=payment.evidence_content_type or 'application/octet-stream',
                        filename=payment.evidence_name or 'payment-evidence',
                        headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-store'})


@router.post('/{order_id}/payments/{payment_id}/reconcile')
def reconcile_payment(order_id: str, payment_id: str, payload: s.PaymentReconcile,
                      db=Depends(session_db), user=Depends(require('payment_records:write'))):
    order = get_order_or_404(db, user, order_id, lock=True)
    payment = _payment_for_order(db, user, order_id, payment_id)
    if payment.record_type != 'real' or payment.reconciliation_status != 'pending':
        raise HTTPException(409, '只有待核对的真实收款可以核对')
    try:
        _checked_evidence_path(payment)
    except HTTPException as exc:
        raise HTTPException(409, '凭据文件缺失或已变化，不能完成核对') from exc
    before = payment_snapshot(payment)
    payment.reconciliation_status = 'verified'
    payment.verified_at = datetime.now(timezone.utc).replace(tzinfo=None)
    payment.verified_by = user.id
    db.flush()
    result = payment_snapshot(payment)
    record_audit(db, user, 'payment_records', payment.id, 'reconcile',
                 before=jsonable_encoder(before), after=jsonable_encoder(result))
    db.commit()
    return result
