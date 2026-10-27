from pathlib import Path
import re
import tempfile
import unittest
import settings
from migrate_install import install_cron_launcher

PROJECT = Path(__file__).resolve().parents[1]

class SafetyTests(unittest.TestCase):
    def test_installed_cron_launcher_stays_inside_scripts(self):
        with tempfile.TemporaryDirectory(dir=PROJECT) as directory:
            scripts = Path(directory)
            target = scripts/'unified_notify_sender.py'
            target.symlink_to(PROJECT/'cron_launcher.py')
            self.assertFalse(target.resolve().is_relative_to(scripts))
            install_cron_launcher(scripts)
            self.assertFalse(target.is_symlink())
            self.assertTrue(target.resolve().is_relative_to(scripts))
            self.assertEqual(target.read_bytes(), (PROJECT/'cron_launcher.py').read_bytes())

    def test_sources_do_not_embed_site_settings_or_tokens(self):
        cfg = settings.load()
        private=[]
        for key in ('channel_id','owner_user_id'):
            value=str(cfg[key])
            if len(value)>4:private.append(value)
        for key in ('action_category','delivery_namespace','runtime_path','db_path'):
            value=str(cfg[key])
            if value != str(settings.validate({})[key]):private.append(value)
        for path in PROJECT.rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts or any(part.startswith('.') for part in path.relative_to(PROJECT).parts):
                continue
            try:text=path.read_text()
            except UnicodeError:continue
            with self.subTest(file=str(path.relative_to(PROJECT))):
                for value in private:
                    self.assertNotIn(value,text,'site-specific setting embedded')
                self.assertIsNone(re.search(r'(?<!\d)\d{6,12}:[A-Za-z0-9_-]{30,}',text),'possible bot token')
                self.assertIsNone(re.search(r'(?<![a-f0-9])[a-f0-9]{32,64}(?![a-f0-9])',text),'possible embedded credential')
