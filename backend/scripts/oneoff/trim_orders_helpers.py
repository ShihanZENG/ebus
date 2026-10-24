# 一次性编辑脚本：删除 orders.py 中与 orders_common.py 重复的辅助函数定义，改为导入。
from pathlib import Path

path = Path(r'E:\06-接口与数据\跨境电商系统开发\backend\app\orders.py')
text = path.read_text(encoding='utf-8')

start = text.index('CENTS = Decimal')
end = text.index('def validate_order_refs')
removed = text[start:end]
assert 'def get_order_or_404' in removed and 'def payment_snapshot' in removed, 'anchor mismatch'

imports = (
    'from . import oms_state\n'
    'from .orders_common import (CENTS, money, auditable, order_snapshot, item_snapshot,\n'
    '                            payment_snapshot, after_sale_snapshot, recognized_payment_condition,\n'
    '                            visible_shop_ids, ensure_warehouse_scope, get_order_or_404)\n\n\n'
)
text = text[:start] + imports + text[end:]
path.write_text(text, encoding='utf-8')
print('ok, removed', removed.count(chr(10)), 'lines')
