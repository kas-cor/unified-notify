#!/usr/bin/env python3
"""One-site setup: preview by default; --apply installs and updates managed instructions.
No Telegram sends, credential discovery, data migration or Gateway restarts.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parent
BEGIN = '<!-- unified-notify:begin -->'
END = '<!-- unified-notify:end -->'


SHARED_SKILL = 'unified-notify-usage'


def update_soul(text):
    if text.count(BEGIN) != text.count(END) or text.count(BEGIN)>1:
        raise ValueError('invalid managed instruction markers')
    if BEGIN in text:
        start=text.index(BEGIN);end=text.index(END)+len(END)
        if end<start:raise ValueError('invalid managed instruction marker order')
        text=text[:start]+text[end:]
    lines=text.splitlines(keepends=True)
    retained=[];skip=False
    for line in lines:
        if line.startswith('## '):
            lowered=line.casefold()
            skip=('единые уведомления' in lowered or 'единый канал уведомлений' in lowered)
        if not skip:retained.append(line)
    before=''.join(retained).rstrip()
    return before+'\n' if before else ''


def profiles_plan(root, config_reader):
    root=Path(root)
    homes=[('default',root)]
    profiles=root/'profiles'
    if profiles.exists():
        homes.extend((p.name,p) for p in sorted(profiles.iterdir()) if p.is_dir() and re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}',p.name))
    result=[]
    for name,home in homes:
        if not (home/'config.yaml').is_file():continue
        if __package__:
            from .settings import plugin_enabled
        else:
            from settings import plugin_enabled
        enabled = plugin_enabled(config_reader(home)) and (home/'plugins/unified-notify').is_dir()
        result.append({'name':name,'home':home,'native_plugin':enabled})
    if sum(x['native_plugin'] for x in result)!=1:raise ValueError('expected exactly one enabled installed transport plugin')
    return result


def config_for(home):
    from hermes_constants import set_hermes_home_override,reset_hermes_home_override
    from hermes_cli.config import load_config_readonly
    token=set_hermes_home_override(home)
    try:return load_config_readonly() or {}
    finally:reset_hermes_home_override(token)


def atomic_text(path, text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    mode=path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd,name=tempfile.mkstemp(prefix='.unified-notify-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            os.fchmod(stream.fileno(),mode);stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def run_cli(profile, args):
    executable=shutil.which('hermes')
    if executable is None:raise RuntimeError('Hermes CLI not found')
    result=subprocess.run([executable,'-p',profile,*args],capture_output=True,text=True,timeout=120)
    if result.returncode:raise RuntimeError('Hermes CLI step failed for profile '+profile)


def sync_native_plugin(home, name, native_plugin, backup, *, cli_runner=run_cli, config_reader=config_for):
    home=Path(home);target=home/'plugins/unified-notify'
    plugins=config_reader(home).get('plugins',{})
    if not native_plugin:
        # Producers use the shared CLI and auto-loaded instruction, not native hooks.
        if 'unified-notify' in plugins.get('enabled',[]):
            cli_runner(name,['plugins','disable','unified-notify'])
        if target.exists() or target.is_symlink():
            target.rename(Path(backup)/'previous-plugin')
        return
    if not (target.is_symlink() and target.resolve()==PROJECT):
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists() or target.is_symlink():target.rename(Path(backup)/'previous-plugin')
        target.symlink_to(PROJECT,target_is_directory=True)
    if 'unified-notify' not in plugins.get('enabled',[]) or 'unified-notify' in plugins.get('disabled',[]):
        cli_runner(name,['plugins','enable','unified-notify'])


def apply_plan(plan, base, root):
    from hermes_constants import set_hermes_home_override,reset_hermes_home_override
    from hermes_cli.plugins_settings import save_plugin_settings
    backup=Path(root)/'backups'/('unified-notify-setup-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True,mode=0o700)
    # Validate every document before the first modification.
    updates=[]
    for entry in plan:
        path=entry['home']/'SOUL.md';old=path.read_text() if path.exists() else ''
        new=update_soul(old)
        updates.append((entry,path,old,new))
    if __package__:
        from .shared_prompt import ensure_shared_prompt
    else:
        from shared_prompt import ensure_shared_prompt
    ensure_shared_prompt(plan,backup,PROJECT)
    for entry,path,old,new in updates:
        home=entry['home'];name=entry['name'];folder=backup/name;folder.mkdir(mode=0o700)
        shutil.copy2(home/'config.yaml',folder/'config.yaml');(folder/'config.yaml').chmod(0o600)
        if path.exists():shutil.copy2(path,folder/'SOUL.md')
        values=base if entry['native_plugin'] else {}
        token=set_hermes_home_override(home)
        try:save_plugin_settings('unified-notify',PROJECT,values)
        finally:reset_hermes_home_override(token)
        if new!=old:atomic_text(path,new)
        sync_native_plugin(home,name,entry['native_plugin'],folder)
        print('configured',name,'transport' if entry['native_plugin'] else 'CLI',flush=True)
    transport=next(x for x in plan if x['native_plugin'])
    scripts=transport['home']/'scripts';scripts.mkdir(parents=True,exist_ok=True)
    launcher=(PROJECT/'cron_launcher.py').read_text().replace("'/projects/unified-notify/compat.py'",repr(str(PROJECT/'compat.py')))
    atomic_text(scripts/'unified_notify_sender.py',launcher)
    jobs_path=transport['home']/'cron/jobs.json';data=json.loads(jobs_path.read_text()) if jobs_path.exists() else []
    jobs=data if isinstance(data,list) else data.get('jobs',[])
    matches=[j for j in jobs if j.get('name')=='unified-notify-tick' or j.get('script')=='unified_notify_sender.py']
    if len(matches)>1:raise RuntimeError('duplicate sender jobs; inspect manually')
    if not matches:
        run_cli(transport['name'],['cron','create','* * * * *','--name','unified-notify-tick','--script','unified_notify_sender.py','--no-agent','--deliver','local'])
    elif matches[0].get('script')!='unified_notify_sender.py' or not matches[0].get('no_agent'):
        run_cli(transport['name'],['cron','edit',matches[0]['id'],'--script','unified_notify_sender.py','--no-agent'])
    print('backup',backup)
    print('Apply complete. No Gateway restart or Telegram test message was performed.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root-home',type=Path,default=Path.home()/'.hermes')

    parser.add_argument('--settings-file',type=Path)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    root=args.root_home.expanduser().resolve();sys.path.insert(0,str(root/'hermes-agent'))
    if __package__:
        from .settings import DEFAULTS,validate
    else:
        from settings import DEFAULTS,validate
    if root != (Path.home()/'.hermes').resolve():
        raise ValueError('root home must be the shared default Hermes home')
    plan=profiles_plan(root,config_for)
    transport=next(x for x in plan if x['native_plugin'])
    raw=config_for(transport['home']).get('plugins',{}).get('entries',{}).get('unified-notify',{}).get('settings',{})
    base={key:raw.get(key,default) for key,default in DEFAULTS.items()}
    if args.settings_file:base.update(json.loads(args.settings_file.read_text()))

    print(json.dumps({'profiles':[{'name':x['name'],'native_plugin':x['native_plugin']} for x in plan],'apply':args.apply},ensure_ascii=False,indent=2))
    unknown=set(base)-set(DEFAULTS)
    if unknown:raise ValueError('unsupported settings keys')
    try:
        validate(base, transport=True)
    except ValueError as exc:
        print('Configure the transport plugin once (channel_id, owner_user_id), '
              'or pass --settings-file with local non-secret settings. '+str(exc),file=sys.stderr)
        return 2
    if args.apply:apply_plan(plan,base,root)
    else:print('Preview only; use --apply after reviewing this plan.')
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print('Setup failed: '+type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)
