import sys
from types import ModuleType, SimpleNamespace

import pytest
import diagnostics


def home_with_token(tmp_path):
    home = tmp_path / 'profiles' / 'cron'
    home.mkdir(parents=True)
    (home / '.env').write_text('TELEGRAM_BOT_TOKEN=fake-secret\n')
    return home


def test_live_standalone_connected(tmp_path, monkeypatch):
    home = home_with_token(tmp_path)
    snapshot = {'pid': 44, 'gateway_state': 'running', 'platforms': {'telegram': {'state': 'connected'}}}
    monkeypatch.setattr(diagnostics, '_runtime', lambda home: (44, 'pid', snapshot, True))
    result = diagnostics.telegram_status(home)
    assert result['status'] == 'connected'
    assert result['enabled'] is True and result['configured'] is True
    assert result['pid'] == 44 and 'fake-secret' not in repr(result)


@pytest.mark.parametrize('snapshot,verified,expected', [
    (None, False, 'missing'),
    ({'gateway_state': 'running', 'platforms': {'telegram': {'state': 'connected'}}}, False, 'stale'),
    ({'gateway_state': 'running', 'platforms': {}}, True, 'missing'),
    ({'gateway_state': 'stopped', 'platforms': {'telegram': {'state': 'connected'}}}, True, 'stale'),
    ({'gateway_state': 'running', 'platforms': {'telegram': {'state': 'retrying'}}}, True, 'retrying'),
    ({'gateway_state': 'running', 'platforms': {'telegram': {'state': 'unrecognized'}}}, True, 'unknown'),
])
def test_runtime_states_fail_closed(tmp_path, monkeypatch, snapshot, verified, expected):
    home = home_with_token(tmp_path)
    monkeypatch.setattr(diagnostics, '_runtime', lambda home: (44, 'pid', snapshot, verified))
    assert diagnostics.telegram_status(home)['status'] == expected


def test_disabled_beats_configured(tmp_path, monkeypatch):
    home = home_with_token(tmp_path)
    (home / 'config.yaml').write_text('platforms:\n  telegram:\n    enabled: false\n')
    monkeypatch.setattr(diagnostics, '_runtime', lambda home: (None, 'none', None, False))
    result = diagnostics.telegram_status(home)
    assert result['status'] == 'disabled' and result['configured'] is True


def test_unconfigured_does_not_borrow_process_env(tmp_path, monkeypatch):
    home = tmp_path / 'p'
    home.mkdir()
    (home / 'config.yaml').write_text('platforms:\n  telegram:\n    enabled: true\n')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'foreign-secret')
    monkeypatch.setattr(diagnostics, '_runtime', lambda home: (None, 'none', None, False))
    result = diagnostics.telegram_status(home)
    assert result['status'] == 'unconfigured' and not result['configured']


def fake_gateway(monkeypatch, snapshot, live, mux, verified_pid):
    gateway = ModuleType('gateway')
    status = ModuleType('gateway.status')
    status.get_running_pid = lambda *a, **kw: None
    status.read_runtime_status = lambda path: snapshot
    status.resolve_gateway_liveness = lambda **kw: live
    status.multiplexer_liveness_for_profile = lambda home: mux
    status.get_runtime_status_running_pid = lambda snapshot, **kw: verified_pid
    status.profile_name_for_home = lambda home: home.name
    gateway.status = status
    monkeypatch.setitem(sys.modules, 'gateway', gateway)
    monkeypatch.setitem(sys.modules, 'gateway.status', status)


def test_mux_pid_ladder_uses_host_snapshot_and_profile_key(tmp_path, monkeypatch):
    home = home_with_token(tmp_path)
    old = {'pid': 99, 'gateway_state': 'running', 'platforms': {'telegram': {'state': 'connected'}}}
    host = {'pid': 44, 'hermes_home': str(tmp_path), 'gateway_state': 'running',
            'platforms': {'telegram': {'state': 'connected'}, 'cron:telegram': {'state': 'retrying'}}}
    fake_gateway(monkeypatch, old, SimpleNamespace(running=True, pid=44, source='pid'), (44, host), 44)
    result = diagnostics.telegram_status(home)
    assert result['gateway_source'] == 'multiplexer' and result['status'] == 'retrying'


def test_mux_old_snapshot_pid_cannot_claim_connected(tmp_path, monkeypatch):
    home = home_with_token(tmp_path)
    host = {'pid': 33, 'hermes_home': str(tmp_path), 'gateway_state': 'running',
            'platforms': {'cron:telegram': {'state': 'connected'}}}
    fake_gateway(monkeypatch, None, SimpleNamespace(running=True, pid=44, source='multiplexer'), (44, host), 33)
    assert diagnostics.telegram_status(home)['status'] == 'stale'


def test_missing_mux_profile_entry_cannot_borrow_default(tmp_path, monkeypatch):
    home = home_with_token(tmp_path)
    host = {'pid': 44, 'hermes_home': str(tmp_path), 'gateway_state': 'running',
            'platforms': {'telegram': {'state': 'connected'}}}
    fake_gateway(monkeypatch, None, SimpleNamespace(running=True, pid=44, source='multiplexer'), (44, host), 44)
    assert diagnostics.telegram_status(home)['status'] == 'missing'


def test_probe_failure_is_unknown_without_leaking_exception(tmp_path, monkeypatch):
    home = home_with_token(tmp_path)
    def fail(home):
        raise RuntimeError('fake-secret')
    monkeypatch.setattr(diagnostics, '_runtime', fail)
    result = diagnostics.telegram_status(home)
    assert result['status'] == 'unknown' and 'fake-secret' not in repr(result)
