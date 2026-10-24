import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.config import ROOT
from app.db import build_engine


def test_migration_adds_lim_tables_and_keeps_purchase_agent_tables(tmp_path, monkeypatch):
    url = 'sqlite:///' + str(tmp_path / 'lim-migration.db').replace('\\', '/')
    monkeypatch.setenv('DATABASE_URL', url)
    command.upgrade(Config(str(ROOT / 'alembic.ini')), 'head')
    engine = build_engine(url)
    try:
        names = set(inspect(engine).get_table_names())
        assert {
            'lim_agents', 'lim_tools', 'lim_runs', 'lim_spans', 'lim_tool_invocations',
            'lim_eval_datasets', 'lim_eval_cases', 'lim_eval_runs', 'lim_eval_case_results',
            'lim_eval_comparisons',
        }.issubset(names)
        assert {'agent_runs', 'agent_tool_calls', 'purchase_agent_drafts'}.issubset(names)
        config = Config(str(ROOT / 'alembic.ini'))
        scripts = ScriptDirectory.from_config(config)
        ancestors = {revision.revision for revision in scripts.walk_revisions()}
        assert '0028' in ancestors
        with engine.connect() as connection:
            assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == scripts.get_current_head()
    finally:
        engine.dispose()


def test_eval_comparison_migration_round_trips_in_isolated_sqlite(tmp_path, monkeypatch):
    url = 'sqlite:///' + str(tmp_path / 'lim-comparison-migration.db').replace('\\', '/')
    monkeypatch.setenv('DATABASE_URL', url)
    config = Config(str(ROOT / 'alembic.ini'))
    command.upgrade(config, '0036')
    engine = build_engine(url)
    try:
        assert 'lim_eval_comparisons' not in inspect(engine).get_table_names()
        command.upgrade(config, '0037')
        assert 'lim_eval_comparisons' in inspect(engine).get_table_names()
        command.downgrade(config, '0036')
        assert 'lim_eval_comparisons' not in inspect(engine).get_table_names()
        command.upgrade(config, 'head')
        assert 'lim_eval_comparisons' in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == '0037'
    finally:
        engine.dispose()
