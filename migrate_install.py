#!/usr/bin/env python3
"""Install a local source link and a regular cron launcher; never send or restart.
Site-specific configuration is supplied separately, never embedded in the source.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

PROJECT = Path(__file__).resolve().parent


def install_cron_launcher(scripts, filename='unified_notify_sender.py'):
    scripts = Path(scripts)
    if Path(filename).name != filename or not filename.endswith('.py'):
        raise ValueError('launcher must be a Python filename')
    scripts.mkdir(parents=True, exist_ok=True)
    staged = scripts/(filename+'.package-stage')
    if staged.exists() or staged.is_symlink():
        raise RuntimeError('unexpected staged launcher')
    shutil.copy2(PROJECT/'cron_launcher.py', staged)
    os.replace(staged, scripts/filename)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root-home', type=Path, default=Path.home()/'.hermes')
    parser.add_argument('--profile', default='cron')
    parser.add_argument('--settings-file', type=Path)
    args = parser.parse_args()
    root = args.root_home.expanduser().resolve()
    sys.path.insert(0,str(root/'hermes-agent'))
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from hermes_cli.plugins_settings import save_plugin_settings
    if args.profile != 'default' and (Path(args.profile).name != args.profile or args.profile.startswith('.')):
        raise ValueError('invalid profile')
    home = root if args.profile == 'default' else root/'profiles'/args.profile
    if not home.is_dir():
        raise ValueError('profile does not exist')
    backup = home/'backups'/('unified-notify-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    backup.mkdir(parents=True, mode=0o700)
    shutil.copy2(home/'config.yaml',backup/'config.yaml')
    (backup/'config.yaml').chmod(0o600)
    target = home/'plugins/unified-notify'
    if not (target.is_symlink() and target.resolve()==PROJECT):
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            target.rename(backup/'previous-plugin')
        target.symlink_to(PROJECT, target_is_directory=True)
    if args.settings_file:
        values = json.loads(args.settings_file.read_text())
        token = set_hermes_home_override(home)
        try:
            save_plugin_settings('unified-notify',PROJECT,values)
        finally:
            reset_hermes_home_override(token)
    install_cron_launcher(home/'scripts')
    print('Installed source link and launcher; settings and enablement are profile-owned.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
