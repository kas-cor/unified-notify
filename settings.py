"""User settings and internal shared notification invariants."""
from pathlib import Path

PLUGIN_ID = 'unified-notify'
DEFAULTS = {'channel_id': 0, 'owner_user_id': 0, 'batch_size': 10, 'spacing_seconds': 1.0}


def validate(values, *, transport=False):
    result = {key: values.get(key, default) for key, default in DEFAULTS.items()}
    root = Path.home() / '.hermes'
    result.update(root_home=root, db_path=root / 'data/unified-notify.sqlite3',
                  action_category='needs_owner', delivery_namespace='unified-notify',
                  runtime_path='runtime/unified-notify')
    for key in ('channel_id', 'owner_user_id', 'batch_size'):
        if isinstance(result[key], bool) or not isinstance(result[key], int):
            raise ValueError(key + ' must be an integer')
    if not 1 <= result['batch_size'] <= 10:
        raise ValueError('batch_size must be between 1 and 10')
    spacing = result['spacing_seconds']
    if isinstance(spacing, bool) or not isinstance(spacing, (int, float)) or not 0 <= spacing <= 30:
        raise ValueError('spacing_seconds must be between 0 and 30')
    if transport and result['channel_id'] == 0:
        raise ValueError('channel_id must identify a Telegram chat')
    if transport and result['owner_user_id'] <= 0:
        raise ValueError('transport requires an explicit owner identity')
    return result


def load(home=None):
    from hermes_cli.config import load_config_readonly
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    token = set_hermes_home_override(home) if home is not None else None
    try:
        config = load_config_readonly() or {}
        entry = config.get('plugins', {}).get('entries', {}).get(PLUGIN_ID) or {}
        return validate(entry.get('settings') or {})
    finally:
        if token is not None:
            reset_hermes_home_override(token)


def from_context(ctx, *, transport=False):
    return validate({key: ctx.get_config(key, default) for key, default in DEFAULTS.items()}, transport=transport)


def plugin_enabled(config):
    plugins = config.get('plugins') or {}
    return PLUGIN_ID in plugins.get('enabled', []) and PLUGIN_ID not in plugins.get('disabled', [])
