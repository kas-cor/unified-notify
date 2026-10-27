"""Read-only, profile-scoped Telegram gateway diagnostics.

Connected means Hermes reports the adapter connected in a snapshot belonging to
its currently verified gateway process; it is not an active Telegram API probe.
No credentials are returned, logged or sent over the network.
"""
from pathlib import Path


def _enablement(home: Path):
    """Match the dashboard's scoped config/.env enablement, without env leakage."""
    from dotenv import dotenv_values
    from ruamel.yaml import YAML

    config_path = home / 'config.yaml'
    env_path = home / '.env'
    config = YAML(typ='safe').load(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    if config is not None and not isinstance(config, dict):
        raise ValueError('invalid profile configuration')
    platforms = (config or {}).get('platforms') or {}
    if not isinstance(platforms, dict):
        raise ValueError('invalid platform configuration')
    telegram = platforms.get('telegram') or {}
    if not isinstance(telegram, dict):
        raise ValueError('invalid Telegram configuration')
    env = dotenv_values(env_path, interpolate=False) if env_path.exists() else {}
    configured = bool(env.get('TELEGRAM_BOT_TOKEN'))
    raw = telegram.get('enabled')
    enabled = False if raw is False else bool(raw) or configured
    return enabled, configured


def _runtime(home: Path):
    """Resolve Hermes' profile ladder, without stale-file cleanup or credential use."""
    from functools import partial
    from gateway.status import (get_running_pid, get_runtime_status_running_pid,
                                read_runtime_status, resolve_gateway_liveness,
                                multiplexer_liveness_for_profile)
    snapshot = read_runtime_status(home / 'gateway_state.json')
    live = resolve_gateway_liveness(profile_dir=home, runtime=snapshot,
                                    pid_probe=partial(get_running_pid, cleanup_stale=False))
    if not live.running or live.pid is None:
        return None, 'unknown' if live.probe_error else 'none', snapshot, False
    # Hermes' PID rung may already recognize a mux PID through a stale local
    # record, while returning source='pid'. Always resolve the live roster too.
    mux = multiplexer_liveness_for_profile(home)
    source = live.source
    if mux is not None and mux[0] == live.pid:
        snapshot = mux[1]
        source = 'multiplexer'
    if source == 'multiplexer':
        # The host's launch home, not the secondary's stale local file.
        launch_home = snapshot.get('hermes_home') if isinstance(snapshot, dict) else None
        expected_home = Path(launch_home) if isinstance(launch_home, str) and launch_home else None
    else:
        expected_home = home
    # A held PID/lock alone does not validate a snapshot left by an older process.
    verified = (isinstance(snapshot, dict) and expected_home is not None and
                get_runtime_status_running_pid(snapshot, expected_home=expected_home) == live.pid)
    return live.pid, source, snapshot, bool(verified)


def telegram_status(profile_home: str | Path) -> dict:
    """Return a secret-free status dict for one exact Hermes profile home.

    status: connected, disabled, unconfigured, missing, stale, unknown, or the
    adapter's runtime state. `connected` is a persisted adapter report, not a
    promise of successful future delivery or a fresh network round-trip.
    """
    home = Path(profile_home).expanduser().resolve()
    result = {'enabled': None, 'configured': None, 'pid': None,
              'gateway_source': 'unknown', 'gateway_state': None,
              'runtime_state': None, 'status': 'unknown'}
    try:
        enabled, configured = _enablement(home)
        result.update(enabled=enabled, configured=configured)
        pid, source, snapshot, verified = _runtime(home)
        result.update(pid=pid, gateway_source=source)
        if isinstance(snapshot, dict):
            result['gateway_state'] = snapshot.get('gateway_state')
            platforms = snapshot.get('platforms')
            if isinstance(platforms, dict):
                if source == 'multiplexer':
                    from gateway.status import profile_name_for_home
                    name = profile_name_for_home(home)
                    key = 'telegram' if name == 'default' else f'{name}:telegram'
                else:
                    key = 'telegram'
                entry = platforms.get(key)
                if isinstance(entry, dict):
                    state = entry.get('state')
                    if isinstance(state, str):
                        result['runtime_state'] = state
        if not enabled:
            result['status'] = 'disabled'
        elif not configured:
            result['status'] = 'unconfigured'
        elif source == 'unknown':
            result['status'] = 'unknown'
        elif not verified:
            result['status'] = 'stale' if snapshot else 'missing'
        elif result['gateway_state'] not in ('running', 'degraded'):
            result['status'] = 'stale'
        elif result['runtime_state'] is None:
            result['status'] = 'missing'
        else:
            # Only explicit, trusted connected is connected; unknown states stay unknown.
            state = result['runtime_state']
            result['status'] = state if state in {'connected', 'connecting', 'retrying', 'disconnected', 'error', 'stopped'} else 'unknown'
    except Exception:
        # Avoid including exception text: config parsers and filesystem errors can
        # contain credential-bearing lines or paths supplied by the caller.
        result['status'] = 'unknown'
    return result
