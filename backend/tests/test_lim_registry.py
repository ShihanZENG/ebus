import pytest
from pydantic import ValidationError

from app import lim_registry
from app.lim_models import LimTool


OBJECT_SCHEMA = {
    'type': 'object',
    'properties': {'keyword': {'type': 'string'}},
    'required': ['keyword'],
    'additionalProperties': False,
}
OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {'items': {'type': 'array', 'items': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}}},
    'required': ['items'],
    'additionalProperties': False,
}


def _registered_tool(operation_kind='read', status='active'):
    return LimTool(
        tool_id='erp.product.read', version='1.0.0', owner_id='owner-1', service='erp',
        domain='catalog', operation_kind=operation_kind, risk_tier='low', timeout_ms=1000,
        idempotency_mode='not_applicable', scope_policy={'shop': 'server_scope', 'warehouse': 'server_scope'},
        input_schema=OBJECT_SCHEMA, output_schema=OUTPUT_SCHEMA, status=status,
    )


def _agent(**overrides):
    values = {
        'agent_id': 'AG-01', 'display_name': '商品 Agent', 'business_domain': 'catalog',
        'owner_id': 'owner-1', 'version': '1.0.0', 'description': '只读商品查询',
        'input_schema': OBJECT_SCHEMA, 'output_schema': OUTPUT_SCHEMA,
        'allowed_tools': ['erp.product.read'], 'risk_tier': 'low', 'runtime_profile': 'read_only',
    }
    values.update(overrides)
    return lim_registry.AgentDefinition(**values)


def test_agent_without_output_schema_cannot_validate_for_registration():
    issues = lim_registry.validate_agent_definition(_agent(output_schema=None), {'erp.product.read': _registered_tool()})
    assert [issue.code for issue in issues] == ['AGENT_OUTPUT_SCHEMA_REQUIRED']


def test_agent_cannot_reference_unknown_tool():
    issues = lim_registry.validate_agent_definition(_agent(allowed_tools=['erp.unknown']), {})
    assert [issue.code for issue in issues] == ['TOOL_NOT_REGISTERED']


def test_agent_cannot_bind_a_write_tool_even_when_it_is_registered():
    issues = lim_registry.validate_agent_definition(_agent(), {'erp.product.read': _registered_tool(operation_kind='write')})
    assert [issue.code for issue in issues] == ['TOOL_WRITE_NOT_ALLOWED']


def test_tool_reports_missing_scope_risk_and_timeout_metadata():
    tool = lim_registry.ToolDefinition(
        tool_id='erp.product.read', version='1.0.0', owner_id='owner-1', service='erp',
        domain='catalog', operation_kind='read', risk_tier=None, timeout_ms=None,
        idempotency_mode='not_applicable', scope_policy={}, input_schema=OBJECT_SCHEMA, output_schema=OUTPUT_SCHEMA,
    )
    issues = lim_registry.validate_tool_definition(tool)
    assert {issue.code for issue in issues} == {'TOOL_SCOPE_REQUIRED', 'TOOL_RISK_REQUIRED', 'TOOL_TIMEOUT_REQUIRED'}


def test_valid_read_tool_and_agent_have_no_validation_issues():
    tool = _registered_tool()
    assert lim_registry.validate_tool_definition(lim_registry.ToolDefinition.model_validate({
        key: getattr(tool, key) for key in (
            'tool_id', 'version', 'owner_id', 'service', 'domain', 'operation_kind', 'risk_tier',
            'timeout_ms', 'idempotency_mode', 'scope_policy', 'input_schema', 'output_schema', 'status',
        )
    })) == []
    assert lim_registry.validate_agent_definition(_agent(), {tool.tool_id: tool}) == []


def test_invalid_json_schema_is_rejected_with_stable_issue_code():
    definition = _agent(output_schema={'type': 'object', 'required': ['missing'], 'properties': {}})
    assert any(issue.code == 'JSON_SCHEMA_REQUIRED_FIELD_MISSING' for issue in
               lim_registry.validate_agent_definition(definition, {'erp.product.read': _registered_tool()}))


def test_unknown_nested_schema_keywords_fail_closed():
    tool = _registered_tool()
    tool.input_schema = {'type': 'object', 'properties': {'keyword': {'type': 'string', 'minContains': 2}},
                         'required': ['keyword'], 'additionalProperties': False}
    issues = lim_registry.validate_tool_definition(lim_registry.ToolDefinition.model_validate({
        key: getattr(tool, key) for key in (
            'tool_id', 'version', 'owner_id', 'service', 'domain', 'operation_kind', 'risk_tier',
            'timeout_ms', 'idempotency_mode', 'scope_policy', 'input_schema', 'output_schema', 'status',
        )
    }))
    assert any(issue.code == 'JSON_SCHEMA_UNSUPPORTED' for issue in issues)
