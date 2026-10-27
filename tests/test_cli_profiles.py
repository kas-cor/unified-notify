from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


class CLIProfilesTests(unittest.TestCase):
    def test_each_profile_including_transport_enqueues_into_same_database(self):
        with tempfile.TemporaryDirectory(dir=PROJECT) as temp:
            root = Path(temp) / '.hermes'
            db = root / 'data' / 'unified-notify.sqlite3'
            for profile in ('cron', 'notes'):
                home = root / 'profiles' / profile
                home.mkdir(parents=True)
                settings = {'root_home': str(root), 'db_path': str(db),
                            'action_category': 'approval', 'delivery_namespace': 'stable'}
                (home / 'config.yaml').write_text(json.dumps({'plugins': {'entries': {
                    'unified-notify': {'settings': settings}}}}))
                env = dict(os.environ, HERMES_HOME=str(home), HOME=str(Path(temp)))
                payload = {'category': 'needs_owner', 'source': 'test', 'source_id': profile,
                           'title': 'test', 'body': 'test'}
                result = subprocess.run([sys.executable, str(PROJECT / 'cli.py'), 'enqueue', '--stdin'],
                    input=json.dumps(payload), text=True, capture_output=True, env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
            with closing(sqlite3.connect(db)) as connection:
                rows = connection.execute('select origin_profile, category, status from notifications order by origin_profile').fetchall()
            self.assertEqual(rows, [('cron', 'needs_owner', 'pending'), ('notes', 'needs_owner', 'pending')])
