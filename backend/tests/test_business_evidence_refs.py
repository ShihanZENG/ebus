from app.business_evidence_tools import _evidence_ref


def test_evidence_ref_ids_are_unique_across_subjects_with_equal_content():
    first = _evidence_ref(
        'erp.inventory.shop-availability', {'shop_id': 'shop-1', 'sku_code': 'SKU-A'},
        'inventory.shop_available_qty', 3, 'piece', '2026-10-21T00:00:00Z',
        content={'available_qty': 3},
    )
    second = _evidence_ref(
        'erp.inventory.shop-availability', {'shop_id': 'shop-1', 'sku_code': 'SKU-B'},
        'inventory.shop_available_qty', 3, 'piece', '2026-10-21T00:00:00Z',
        content={'available_qty': 3},
    )

    assert first['ref_id'] != second['ref_id']
    assert first['content_hash'] != second['content_hash']
