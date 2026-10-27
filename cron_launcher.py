#!/usr/bin/env python3
"""Installed regular cron launcher; implementation belongs to the plugin."""
import runpy
import sys
_bridge = runpy.run_path('/projects/unified-notify/compat.py')
_module = _bridge['export']('sender', globals())
if __name__ == '__main__':
    try:
        raise SystemExit(_module.main())
    except Exception as exc:
        print('unified-notify: '+type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
