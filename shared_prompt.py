"""Install one shared, pinned instruction before removing per-profile copies."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

SKILL = 'unified-notify-usage'


def _checked(command, **kwargs):
    result = subprocess.run(command, capture_output=True, text=True, timeout=60, **kwargs)
    if result.returncode:
        # Never include a full configuration, subprocess environment or argv in errors.
        raise RuntimeError('Shared prompt installation command failed')


def _pin_managed(names, backup):
    from hermes_cli import managed_scope
    managed = managed_scope.get_managed_dir()
    if managed is None:
        raise RuntimeError('A site-wide managed scope is required for the shared instruction')
    target = managed / 'config.yaml'
    before = target.read_bytes()
    previous = Path(backup) / 'managed-config.before.yaml'
    previous.write_bytes(before)
    previous.chmod(0o600)
    executable = shutil.which('hermes')
    if executable is None:
        raise RuntimeError('Hermes CLI not found')
    with tempfile.TemporaryDirectory(prefix='unified-notify-prompt-') as tmp:
        work = Path(tmp)
        home = work / 'home'; home.mkdir()
        empty = work / 'empty-managed'; empty.mkdir()
        staged = home / 'config.yaml'
        staged.write_bytes(before); staged.chmod(0o600)
        env = dict(os.environ, HERMES_HOME=str(home), HERMES_MANAGED_DIR=str(empty))
        env.pop('HERMES_PROFILE', None)
        # Use the normal schema-aware CLI on a private staging copy, not a YAML edit
        # or HERMES_HOME=/etc/hermes. Publish the resulting managed file as admin.
        _checked([executable, 'config', 'set', 'skills.auto_load', json.dumps(names)], env=env)
        if target.read_bytes() != before:
            raise RuntimeError('Managed configuration changed during setup; retry after inspection')
        prefix = [] if os.geteuid() == 0 else ['sudo', '-n']
        candidate = managed / ('.unified-notify-' + uuid.uuid4().hex + '.yaml')
        _checked([*prefix, 'install', '-o', 'root', '-g', 'root', '-m', '0644', str(staged), str(candidate)])
        if target.read_bytes() != before:
            _checked([*prefix, 'rm', '--', str(candidate)])
            raise RuntimeError('Managed configuration changed before publication')
        _checked([*prefix, 'mv', '-T', '--', str(candidate), str(target)])
    managed_scope.invalidate_managed_cache()
    saved = managed_scope.load_managed_config().get('skills', {}).get('auto_load')
    if saved != names:
        raise RuntimeError('Shared instruction pin verification failed')


def verify_shared_prompts(plan):
    from agent.skill_commands import build_auto_load_prompt
    rows = []
    for entry in plan:
        prompt, loaded, missing = build_auto_load_prompt(home_override=entry['home'])
        if missing or SKILL not in loaded or prompt.count('## Contacting the owner through Unified Notify') != 1:
            raise RuntimeError('Shared instruction did not load for profile ' + entry['name'])
        rows.append({'profile': entry['name'], 'loaded': loaded, 'missing': missing,
                     'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest()})
    return rows


def ensure_shared_prompt(plan, backup, project):
    if __package__:
        from .onboard import config_for
    else:
        from onboard import config_for
    from hermes_cli import managed_scope
    configs = [config_for(entry['home']) for entry in plan]
    roots = []
    pins = []
    for entry, config in zip(plan, configs):
        skills = config.get('skills', {})
        dirs = []
        for value in skills.get('external_dirs') or []:
            path = Path(os.path.expandvars(str(value))).expanduser()
            if not path.is_absolute():
                path = entry['home'] / path
            if path.is_dir():
                dirs.append(path.resolve())
        roots.append(dirs)
        pins.append(list(skills.get('auto_load') or []))
    common = [path for path in roots[0] if all(path in dirs for dirs in roots)]
    if not common:
        raise RuntimeError('Configure one common skills.external_dirs directory before setup')
    if any(names != pins[0] for names in pins):
        raise RuntimeError('Different profile auto-load lists need review before applying a shared pin')
    source = Path(project) / 'skills' / SKILL
    target = common[0] / SKILL
    if target.exists() or target.is_symlink():
        if target.resolve() != source.resolve():
            raise RuntimeError('Shared skill name is already owned by another source')
    else:
        target.symlink_to(source, target_is_directory=True)
    names = list(dict.fromkeys([*pins[0], SKILL]))
    managed_names = managed_scope.load_managed_config().get('skills', {}).get('auto_load')
    if managed_names != names:
        _pin_managed(names, backup)
    rows = verify_shared_prompts(plan)
    (Path(backup) / 'shared-prompt-verification.json').write_text(json.dumps(rows, indent=2))
    print('shared instruction verified', len(rows), 'profiles', flush=True)
