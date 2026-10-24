"""Shared bounded JSON schema checking and trace redaction helpers."""
import re
import math
import json
from decimal import Decimal

from fastapi.encoders import jsonable_encoder


SECRET_KEY = re.compile(r'(?:password|passwd|secret|api[_-]?key|access[_-]?token|authorization|credential|cookie)', re.I)
PII_KEY = re.compile(r'^(?:email|phone|mobile|address|contact|contact_name|recipient_name)$', re.I)
EMAIL_PATTERN = re.compile(r'(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])')
PHONE_PATTERN = re.compile(r'(?<!\d)(?:\+?\d[\d ()-]{7,}\d)(?!\d)')


def json_type_matches(value: object, schema_type: str) -> bool:
    if schema_type == 'object':
        return isinstance(value, dict)
    if schema_type == 'array':
        return isinstance(value, list)
    if schema_type == 'string':
        return isinstance(value, str)
    if schema_type == 'boolean':
        return isinstance(value, bool)
    if schema_type == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == 'number':
        return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
    return value is None if schema_type == 'null' else False


def validate_json_instance(schema: dict, value: object, path: str = '$') -> list[str]:
    expected_type = schema.get('type')
    if expected_type and not json_type_matches(value, expected_type):
        return [f'{path}: expected {expected_type}']
    issues = []
    if 'enum' in schema and not any(type(value) is type(item) and value == item for item in schema['enum']):
        issues.append(f'{path}: not in enum')
    if isinstance(value, dict):
        properties = schema.get('properties', {})
        if len(value) < schema.get('minProperties', 0) or len(value) > schema.get('maxProperties', math.inf):
            issues.append(f'{path}: property count out of range')
        for key in schema.get('required', []):
            if key not in value:
                issues.append(f'{path}.{key}: required')
        if schema.get('additionalProperties', False) is False:
            for key in value.keys() - properties.keys():
                issues.append(f'{path}.{key}: unknown')
        for key, item in value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, dict):
                issues.extend(validate_json_instance(child_schema, item, f'{path}.{key}'))
    elif isinstance(value, list) and isinstance(schema.get('items'), dict):
        if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', math.inf):
            issues.append(f'{path}: item count out of range')
        if schema.get('uniqueItems'):
            try:
                canonical = [json.dumps(item, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                        allow_nan=False) for item in value]
            except (TypeError, ValueError):
                issues.append(f'{path}: items are not valid JSON values')
            else:
                if len(set(canonical)) != len(canonical):
                    issues.append(f'{path}: items must be unique')
        for index, item in enumerate(value):
            issues.extend(validate_json_instance(schema['items'], item, f'{path}[{index}]'))
    if isinstance(value, str):
        if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', math.inf):
            issues.append(f'{path}: string length out of range')
        if 'pattern' in schema and re.search(schema['pattern'], value) is None:
            issues.append(f'{path}: pattern mismatch')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            issues.append(f'{path}: number must be finite')
        for key, compare in (('minimum', lambda x, b: x >= b), ('maximum', lambda x, b: x <= b),
                             ('exclusiveMinimum', lambda x, b: x > b), ('exclusiveMaximum', lambda x, b: x < b)):
            if key in schema and not compare(value, schema[key]):
                issues.append(f'{path}: {key} constraint failed')
    return issues


def sanitize_trace_value(value: object, *, _depth: int = 0) -> object:
    if _depth > 8:
        return '[TRUNCATED]'
    value = jsonable_encoder(value)
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:100]:
            name = str(key)[:120]
            if SECRET_KEY.search(name) or PII_KEY.fullmatch(name):
                result[name] = '[REDACTED]'
            else:
                result[name] = sanitize_trace_value(item, _depth=_depth + 1)
        return result
    if isinstance(value, list):
        return [sanitize_trace_value(item, _depth=_depth + 1) for item in value[:100]]
    if isinstance(value, str):
        text = EMAIL_PATTERN.sub('[REDACTED_EMAIL]', value)
        text = PHONE_PATTERN.sub('[REDACTED_PHONE]', text)
        return text[:2000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    return str(value)[:2000]


def summarize_mock_value(value: object, *, _depth: int = 0) -> object:
    """Preserve mock structure and types without persisting user-supplied scalar values."""
    if _depth > 8:
        return '[TRUNCATED]'
    if isinstance(value, dict):
        return {str(key)[:120]: summarize_mock_value(item, _depth=_depth + 1)
                for key, item in list(value.items())[:100]}
    if isinstance(value, list):
        return [summarize_mock_value(item, _depth=_depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return {'mock_type': 'string'}
    if isinstance(value, bool):
        return {'mock_type': 'boolean'}
    if isinstance(value, (int, float, Decimal)):
        return {'mock_type': 'number'}
    if value is None:
        return {'mock_type': 'null'}
    return {'mock_type': 'unsupported'}
