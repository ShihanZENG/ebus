const ALLOWED_EVIDENCE = {
  pdf: 'application/pdf',
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
}

export function calculatePaymentNet(amount, feeAmount) {
  const gross = Number(amount)
  const fee = Number(feeAmount)
  if (!Number.isFinite(gross) || !Number.isFinite(fee) || gross < 0 || fee < 0 || fee > gross) return null
  return Math.round((gross - fee + Number.EPSILON) * 100) / 100
}

export function evidenceFileError(file) {
  if (!file || !Number.isFinite(file.size) || file.size <= 0) return '请选择有效的收款凭据'
  if (file.size > 10 * 1024 * 1024) return '凭据文件不能超过10 MiB'
  const extension = String(file.name ?? '').split('.').pop()?.toLowerCase()
  const expectedType = ALLOWED_EVIDENCE[extension]
  if (!expectedType) return '凭据仅支持 PDF、PNG、JPG 文件'
  if (file.type !== expectedType) return '凭据文件类型与扩展名不一致'
  return null
}

export function paymentTypeLabel(type) {
  if (type === 'simulated') return '模拟 / 非真实'
  if (type === 'real') return '真实收款'
  return '历史未分类'
}

export function canReconcilePayment(payment, hasWritePermission) {
  return Boolean(hasWritePermission)
    && payment?.record_type === 'real'
    && payment?.reconciliation_status === 'pending'
    && payment?.evidence_status === 'ready'
    && Boolean(payment?.evidence_key)
}
