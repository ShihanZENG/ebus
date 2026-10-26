from collections.abc import Mapping
import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .lim_models import LimTool


RISK_TIERS = {'low', 'medium', 'high', 'critical'}
JSON_TYPES = {'object', 'array', 'string', 'number', 'integer', 'boolean', 'null'}
UNSUPPORTED_SCHEMA_KEYS = {'$ref', 'oneOf', 'anyOf', 'allOf', 'not', 'patternProperties', 'definitions', '$defs'}
SUPPORTED_SCHEMA_KEYS = {'type', 'properties', 'required', 'additionalProperties', 'items', 'enum', 'pattern',
                        'minLength', 'maxLength', 'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum',
                        'minItems', 'maxItems', 'uniqueItems', 'minProperties', 'maxProperties'}


class ValidationIssue(BaseModel):
    code: str
    field: str
    message: str


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    tool_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=32)
    owner_id: str = Field(min_length=1, max_length=36)
    service: str = Field(min_length=1, max_length=80)
    domain: str = Field(min_length=1, max_length=64)
    operation_kind: Literal['read', 'write']
    risk_tier: str | None = None
    timeout_ms: int | None = None
    rate_limit: dict | None = None
    idempotency_mode: str | None = None
    scope_policy: dict = Field(default_factory=dict)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict | None = None
    status: Literal['draft', 'active', 'archived'] = 'draft'


class AgentDefinition(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    agent_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=120)
    business_domain: str = Field(min_length=1, max_length=64)
    owner_id: str = Field(min_length=1, max_length=36)
    version: str = Field(min_length=1, max_length=32)
    description: str = Field(default='', max_length=1000)
    capability_tags: list[str] = Field(default_factory=list, max_length=30)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict | None = None
    allowed_tools: list[str] = Field(default_factory=list, max_length=50)
    model_policy_ref: str | None = Field(default=None, max_length=120)
    risk_tier: str | None = None
    runtime_profile: str = 'read_only'


def _schema_issues(schema: object, field: str) -> list[ValidationIssue]:
    if not isinstance(schema, dict) or schema.get('type') != 'object':
        return [ValidationIssue(code='JSON_SCHEMA_OBJECT_REQUIRED', field=field,
                                message='Schema 根节点必须是 object')]
    issues: list[ValidationIssue] = []
    unsupported = sorted(set(schema) - SUPPORTED_SCHEMA_KEYS)
    unsupported.extend(_inapplicable_schema_keys(schema))
    unsupported = sorted(set(unsupported))
    if unsupported:
        issues.append(ValidationIssue(code='JSON_SCHEMA_UNSUPPORTED', field=field,
                                      message=f'当前不支持或未知 Schema 关键字：{", ".join(unsupported)}'))
    properties = schema.get('properties', {})
    if not isinstance(properties, dict):
        issues.append(ValidationIssue(code='JSON_SCHEMA_PROPERTIES_INVALID', field=f'{field}.properties',
                                      message='properties 必须是对象'))
        properties = {}
    required = schema.get('required', [])
    if not isinstance(required, list) or not all(isinstance(name, str) for name in required):
        issues.append(ValidationIssue(code='JSON_SCHEMA_REQUIRED_INVALID', field=f'{field}.required',
                                      message='required 必须是字符串数组'))
    else:
        missing = sorted(set(required) - set(properties))
        if missing:
            issues.append(ValidationIssue(code='JSON_SCHEMA_REQUIRED_FIELD_MISSING', field=f'{field}.required',
                                          message=f'required 字段未声明：{", ".join(missing)}'))
    if schema.get('additionalProperties', False) is not False:
        issues.append(ValidationIssue(code='JSON_SCHEMA_ADDITIONAL_PROPERTIES', field=f'{field}.additionalProperties',
                                      message='工具 Schema 必须显式禁止未声明字段'))
    for name, child in properties.items():
        issues.extend(_nested_schema_issues(child, f'{field}.properties.{name}'))
    if schema.get('type') == 'array':
        if 'items' not in schema:
            issues.append(ValidationIssue(code='JSON_SCHEMA_ARRAY_ITEMS_REQUIRED', field=f'{field}.items', message='数组必须声明 items Schema'))
        else:
            issues.extend(_nested_schema_issues(schema['items'], f'{field}.items'))
    enum = schema.get('enum')
    if 'enum' in schema and (not isinstance(enum, list) or not enum):
        issues.append(ValidationIssue(code='JSON_SCHEMA_ENUM_INVALID', field=f'{field}.enum', message='enum 必须是非空数组'))
    elif 'enum' in schema and any(not _json_type_matches(item, schema['type']) for item in enum):
        issues.append(ValidationIssue(code='JSON_SCHEMA_ENUM_INVALID', field=f'{field}.enum', message='enum 值必须匹配声明的 JSON type'))
    for key, expected in (('minLength', int), ('maxLength', int), ('minItems', int), ('maxItems', int),
                          ('minProperties', int), ('maxProperties', int)):
        if key in schema and (isinstance(schema[key], bool) or not isinstance(schema[key], expected) or schema[key] < 0):
            issues.append(ValidationIssue(code='JSON_SCHEMA_BOUND_INVALID', field=f'{field}.{key}', message=f'{key} 必须为非负整数'))
    for key in ('minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum'):
        if key in schema and (isinstance(schema[key], bool) or not isinstance(schema[key], (int, float)) or not math.isfinite(schema[key])):
            issues.append(ValidationIssue(code='JSON_SCHEMA_BOUND_INVALID', field=f'{field}.{key}', message=f'{key} 必须为有限数值'))
    if 'pattern' in schema:
        try:
            if not isinstance(schema['pattern'], str):
                raise TypeError
            re.compile(schema['pattern'])
        except (re.error, TypeError):
            issues.append(ValidationIssue(code='JSON_SCHEMA_PATTERN_INVALID', field=f'{field}.pattern', message='pattern 必须是有效正则表达式'))
    if 'uniqueItems' in schema and not isinstance(schema['uniqueItems'], bool):
        issues.append(ValidationIssue(code='JSON_SCHEMA_UNIQUE_ITEMS_INVALID', field=f'{field}.uniqueItems', message='uniqueItems 必须为布尔值'))
    return issues


def _nested_schema_issues(schema: object, field: str) -> list[ValidationIssue]:
    if not isinstance(schema, dict) or schema.get('type') not in JSON_TYPES:
        return [ValidationIssue(code='JSON_SCHEMA_PROPERTY_TYPE_REQUIRED', field=field,
                                message='每个属性必须声明受支持的 JSON type')]
    issues = []
    unsupported = sorted(set(schema) - SUPPORTED_SCHEMA_KEYS)
    unsupported.extend(_inapplicable_schema_keys(schema))
    unsupported = sorted(set(unsupported))
    if unsupported:
        issues.append(ValidationIssue(code='JSON_SCHEMA_UNSUPPORTED', field=field,
                                      message=f'当前不支持或未知 Schema 关键字：{", ".join(unsupported)}'))
    if schema.get('type') == 'object':
        properties = schema.get('properties', {})
        if not isinstance(properties, dict):
            issues.append(ValidationIssue(code='JSON_SCHEMA_PROPERTIES_INVALID', field=f'{field}.properties', message='properties 必须是对象'))
        else:
            for name, child in properties.items():
                issues.extend(_nested_schema_issues(child, f'{field}.properties.{name}'))
        required = schema.get('required', [])
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            issues.append(ValidationIssue(code='JSON_SCHEMA_REQUIRED_INVALID', field=f'{field}.required', message='required 必须是字符串数组'))
        elif not set(required) <= set(properties):
            issues.append(ValidationIssue(code='JSON_SCHEMA_REQUIRED_FIELD_MISSING', field=f'{field}.required', message='required 字段必须在 properties 中声明'))
        if schema.get('additionalProperties', False) is not False:
            issues.append(ValidationIssue(code='JSON_SCHEMA_ADDITIONAL_PROPERTIES', field=f'{field}.additionalProperties', message='工具 Schema 必须显式禁止未声明字段'))
    if schema.get('type') == 'array':
        if 'items' not in schema:
            issues.append(ValidationIssue(code='JSON_SCHEMA_ARRAY_ITEMS_REQUIRED', field=f'{field}.items', message='数组必须声明 items Schema'))
        else:
            issues.extend(_nested_schema_issues(schema['items'], f'{field}.items'))
    # Apply scalar constraint syntax checks by reusing the public recursive validation logic.
    for key, expected in (('minLength', int), ('maxLength', int), ('minItems', int), ('maxItems', int),
                          ('minProperties', int), ('maxProperties', int)):
        if key in schema and (isinstance(schema[key], bool) or not isinstance(schema[key], expected) or schema[key] < 0):
            issues.append(ValidationIssue(code='JSON_SCHEMA_BOUND_INVALID', field=f'{field}.{key}', message=f'{key} 必须为非负整数'))
    for key in ('minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum'):
        if key in schema and (isinstance(schema[key], bool) or not isinstance(schema[key], (int, float)) or not math.isfinite(schema[key])):
            issues.append(ValidationIssue(code='JSON_SCHEMA_BOUND_INVALID', field=f'{field}.{key}', message=f'{key} 必须为有限数值'))
    if 'pattern' in schema:
        try:
            if not isinstance(schema['pattern'], str): raise TypeError
            re.compile(schema['pattern'])
        except (re.error, TypeError):
            issues.append(ValidationIssue(code='JSON_SCHEMA_PATTERN_INVALID', field=f'{field}.pattern', message='pattern 必须是有效正则表达式'))
    if 'enum' in schema and (not isinstance(schema['enum'], list) or not schema['enum']):
        issues.append(ValidationIssue(code='JSON_SCHEMA_ENUM_INVALID', field=f'{field}.enum', message='enum 必须是非空数组'))
    elif 'enum' in schema and any(not _json_type_matches(item, schema['type']) for item in schema['enum']):
        issues.append(ValidationIssue(code='JSON_SCHEMA_ENUM_INVALID', field=f'{field}.enum', message='enum 值必须匹配声明的 JSON type'))
    if 'uniqueItems' in schema and not isinstance(schema['uniqueItems'], bool):
        issues.append(ValidationIssue(code='JSON_SCHEMA_UNIQUE_ITEMS_INVALID', field=f'{field}.uniqueItems', message='uniqueItems 必须为布尔值'))
    return issues


def _inapplicable_schema_keys(schema: dict) -> list[str]:
    applicable = {
        'object': {'properties', 'required', 'additionalProperties', 'minProperties', 'maxProperties'},
        'array': {'items', 'minItems', 'maxItems', 'uniqueItems'},
        'string': {'pattern', 'minLength', 'maxLength'},
        'number': {'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum'},
        'integer': {'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum'},
    }.get(schema.get('type'), set())
    universal = {'type', 'enum'}
    return sorted(key for key in schema if key not in applicable | universal)


def _json_type_matches(value: object, schema_type: str) -> bool:
    if schema_type == 'object': return isinstance(value, dict)
    if schema_type == 'array': return isinstance(value, list)
    if schema_type == 'string': return isinstance(value, str)
    if schema_type == 'boolean': return isinstance(value, bool)
    if schema_type == 'integer': return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == 'number': return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if schema_type == 'null': return value is None
    return False


def validate_tool_definition(definition: ToolDefinition) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if definition.risk_tier not in RISK_TIERS:
        issues.append(ValidationIssue(code='TOOL_RISK_REQUIRED', field='risk_tier', message='必须指定有效风险等级'))
    if definition.timeout_ms is None or definition.timeout_ms <= 0 or definition.timeout_ms > 120_000:
        issues.append(ValidationIssue(code='TOOL_TIMEOUT_REQUIRED', field='timeout_ms', message='超时必须在 1 到 120000 毫秒之间'))
    if not definition.scope_policy:
        issues.append(ValidationIssue(code='TOOL_SCOPE_REQUIRED', field='scope_policy', message='必须声明服务端数据范围策略'))
    else:
        for key, value in definition.scope_policy.items():
            if key not in {'shop', 'warehouse', 'resource', 'global'} or value not in {'server_scope', 'none'}:
                issues.append(ValidationIssue(code='TOOL_SCOPE_INVALID', field=f'scope_policy.{key}',
                                              message='Scope 只能引用服务端范围，不能接收模型授权值'))
    if definition.operation_kind == 'write' and definition.idempotency_mode != 'required':
        issues.append(ValidationIssue(code='TOOL_IDEMPOTENCY_REQUIRED', field='idempotency_mode',
                                      message='写工具必须声明强制幂等键'))
    issues.extend(_schema_issues(definition.input_schema, 'input_schema'))
    if definition.output_schema is None:
        issues.append(ValidationIssue(code='TOOL_OUTPUT_SCHEMA_REQUIRED', field='output_schema',
                                      message='必须声明输出 Schema'))
    else:
        issues.extend(_schema_issues(definition.output_schema, 'output_schema'))
    return issues


def validate_agent_definition(
    definition: AgentDefinition,
    tools: Mapping[str, LimTool],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if definition.output_schema is None:
        issues.append(ValidationIssue(code='AGENT_OUTPUT_SCHEMA_REQUIRED', field='output_schema',
                                      message='Agent 必须声明输出 Schema'))
    else:
        issues.extend(_schema_issues(definition.output_schema, 'output_schema'))
    issues.extend(_schema_issues(definition.input_schema, 'input_schema'))
    if definition.risk_tier not in RISK_TIERS:
        issues.append(ValidationIssue(code='AGENT_RISK_REQUIRED', field='risk_tier', message='必须指定有效风险等级'))
    if definition.runtime_profile != 'read_only':
        issues.append(ValidationIssue(code='AGENT_RUNTIME_UNSUPPORTED', field='runtime_profile',
                                      message='本阶段只支持 read_only Runtime'))
    if len(set(definition.allowed_tools)) != len(definition.allowed_tools):
        issues.append(ValidationIssue(code='AGENT_TOOL_DUPLICATE', field='allowed_tools', message='工具列表不能重复'))
    for tool_id in definition.allowed_tools:
        tool = tools.get(tool_id)
        if tool is None:
            issues.append(ValidationIssue(code='TOOL_NOT_REGISTERED', field='allowed_tools',
                                          message=f'工具 {tool_id} 尚未注册'))
        elif tool.status != 'active':
            issues.append(ValidationIssue(code='TOOL_NOT_ACTIVE', field='allowed_tools',
                                          message=f'工具 {tool_id} 未处于 active 状态'))
        elif tool.operation_kind == 'write':
            # 本阶段 Runtime 为只读：Agent 一律不得绑定写工具，避免把写 handler
            # 暴露给 LLM 循环（写工具只能在 Sandbox 中做 Schema 级仿真）。
            issues.append(ValidationIssue(code='TOOL_WRITE_NOT_ALLOWED', field='allowed_tools',
                                          message=f'写工具 {tool_id} 不得绑定到只读 Agent'))
    return issues
