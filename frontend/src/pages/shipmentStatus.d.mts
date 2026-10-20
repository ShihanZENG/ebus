export interface ShipmentStatusTag {
  color: string
  text: string
}

export const STATUS_TAG: Record<string, ShipmentStatusTag>
export function canConfirmShipment(status: string): boolean
export function isTrackingNumberValid(value: string): boolean
