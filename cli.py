#!/usr/bin/env python3
"""unified-notify enqueue/status/tick/setup. Credentials are never accepted in argv."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from compat import export


def main():
    if sys.argv[1:] in (['--help'], ['-h']):
        print('Usage: cli.py {enqueue --stdin | status [ID] | check | tick | setup [--apply]}')
        print('setup previews all profile changes; --apply installs settings and managed instructions.')
        return 0
    if sys.argv[1:] == ['check']:
        import json
        from onboard import profiles_plan, config_for
        from diagnostics import telegram_status
        plan = profiles_plan(Path.home() / '.hermes', config_for)
        transport = next(entry for entry in plan if entry['native_plugin'])
        result = telegram_status(transport['home'])
        result['profile'] = transport['name']
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['status'] == 'connected' else 1
    if len(sys.argv) > 1 and sys.argv[1] == 'setup':
        sys.argv.pop(1)
        from onboard import main as setup_main
        return setup_main()
    if len(sys.argv) > 1 and sys.argv[1] == 'tick':
        module = export('sender', {})
        return module.main()
    module = export('store', {})
    return module.main()

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('unified-notify: '+type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
