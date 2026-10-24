from app.lim_safety import validate_json_instance


def test_unique_items_uses_json_deep_equality_independent_of_object_key_order():
    schema = {'type': 'array', 'uniqueItems': True,
              'items': {'type': 'object', 'properties': {'a': {'type': 'integer'}, 'b': {'type': 'integer'}},
                        'required': ['a', 'b'], 'additionalProperties': False}}
    assert any('items must be unique' in issue for issue in validate_json_instance(
        schema, [{'a': 1, 'b': 2}, {'b': 2, 'a': 1}]))
