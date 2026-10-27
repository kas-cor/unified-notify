"""Operational entry points; paths are stable while implementation lives here."""
import importlib.util
from pathlib import Path
import sys
PROJECT = Path(__file__).resolve().parent


def load(kind):
    spec = importlib.util.spec_from_file_location('unified_notify_compat_bridge', PROJECT/'compat.py')
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    return bridge.export(kind, {})


def run(kind):
    return load(kind).main()
