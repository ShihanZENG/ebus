export interface PaymentEvidenceFile {
  name: string
  type: string
  size: number
}

export interface ReconciliationPayment {
  record_type?: string
  reconciliation_status?: string
  evidence_key?: string | null
  evidence_status?: 'staged' | 'ready' | 'missing' | string
}

export function calculatePaymentNet(amount: number, feeAmount: number): number | null
export function evidenceFileError(file: PaymentEvidenceFile | null | undefined): string | null
export function paymentTypeLabel(type: string | undefined): string
export function canReconcilePayment(payment: ReconciliationPayment | null | undefined, hasWritePermission: boolean | undefined): boolean
