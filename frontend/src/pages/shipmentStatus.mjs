export const STATUS_TAG = {
  picking: { color: 'orange', text: '拣货中' },
  shipped: { color: 'green', text: '已发货' },
  cancelled: { color: 'red', text: '已取消' },
}

export function canConfirmShipment(status) {
  return status === 'picking'
}

export function isTrackingNumberValid(value) {
  return value.trim().length > 0
}
