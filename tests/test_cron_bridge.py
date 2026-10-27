import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]

class CronBridgeTests(unittest.TestCase):
    def test_launcher_packaged_sender_profile_discovery(self):
        with tempfile.TemporaryDirectory(dir=PROJECT) as tmp:
            root = Path(tmp) / '.hermes'
            home = root / 'profiles' / 'cron'
            (home / 'plugins' / 'unified-notify').mkdir(parents=True)
            (home / 'config.yaml').write_text('{}')
            launcher = Path(tmp) / 'launcher.py'
            launcher.write_text((PROJECT / 'cron_launcher.py').read_text().replace(
                '/projects/unified-notify/compat.py', str(PROJECT / 'compat.py')))
            code = '''
import runpy, sys
from pathlib import Path
from unittest.mock import patch
ns = runpy.run_path(sys.argv[1])
m = ns['_module']
from _unified_notify_compat import onboard, dispatcher
cfg = {'channel_id': -1001, 'owner_user_id': 123, 'batch_size': 1, 'spacing_seconds': 0}
with patch.object(onboard, 'config_for', return_value={'plugins': {'enabled': ['unified-notify']}}), patch.object(m.settings, 'load', return_value=m.settings.validate(cfg)), patch.object(m, 'load_bot_token', return_value='fake'), patch.object(m, 'send_pending', return_value={'claimed':0,'unknown':0,'failed':0}), patch.object(dispatcher, 'dispatch_replies', return_value={'failed':0}):
    assert m.main() == 0
'''
            env = dict(os.environ, HOME=tmp, HERMES_HOME=str(home), PYTHONDONTWRITEBYTECODE='1',
                       PYTHONPATH=os.environ.get('PYTHONPATH', ''))
            result = subprocess.run([sys.executable, '-c', code, str(launcher)], env=env,
                                    cwd=tmp, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
