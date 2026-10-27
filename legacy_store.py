#!/usr/bin/env python3
"""Compatibility entry point; implementation is owned by unified-notify."""
import runpy
import sys
from pathlib import Path
_bridge = runpy.run_path(str(Path(__file__).resolve().with_name('compat.py')))
_module = _bridge['export']('store', globals())
if __name__ == '__main__':
    try:
        raise SystemExit(_module.main())
    except Exception as exc:
        print('unified-notify: '+type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
