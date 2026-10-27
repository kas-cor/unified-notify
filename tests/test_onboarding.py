import importlib
from pathlib import Path
import tempfile
import unittest

class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.m = importlib.import_module('onboard')

    def test_managed_instruction_is_idempotent_and_preserves_other_sections(self):
        original='# Identity\n\nKeep this.\n\n## Other rules\nDo not change.\n'
        managed=original+'\n'+self.m.BEGIN+'\nRetired instruction\n'+self.m.END+'\n'
        changed=self.m.update_soul(managed)
        self.assertEqual(changed,original)
        self.assertEqual(self.m.update_soul(changed),changed)
        self.assertNotIn(self.m.BEGIN,changed)

    def test_replaces_only_legacy_notification_section(self):
        original='# Identity\nKeep.\n\n## Оперативная связь с владельцем — единые уведомления\nOld command.\n\n## Separate policy\nKeep also.\n'
        changed=self.m.update_soul(original)
        self.assertNotIn('Old command.',changed)
        self.assertIn('## Separate policy\nKeep also.',changed)
        self.assertNotIn(self.m.BEGIN,changed)

    def test_unmatched_markers_fail_closed(self):
        with self.assertRaises(ValueError):self.m.update_soul('Other policy\n'+self.m.BEGIN)

    def test_common_instruction_has_no_fixed_profile_home(self):
        text=(self.m.PROJECT/'skills/unified-notify-usage/SKILL.md').read_text()
        self.assertIn('enqueue --stdin',text)
        self.assertIn('needs_owner',text)
        self.assertIn('<PROFILE_HOME>',text)
        self.assertNotIn('/home/',text)

    def test_producer_installation_is_removed_without_touching_source_or_soul(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            home=Path(tmp)/'profile';(home/'plugins').mkdir(parents=True)
            (home/'SOUL.md').write_text('Keep instructions')
            link=home/'plugins/unified-notify';link.symlink_to(self.m.PROJECT,target_is_directory=True)
            backup=Path(tmp)/'backup';backup.mkdir()
            calls=[]
            self.m.sync_native_plugin(home,'notes',False,backup,
                cli_runner=lambda name,args:calls.append((name,args)),
                config_reader=lambda home:{'plugins':{'enabled':['unified-notify']}})
            self.assertEqual(calls,[('notes',['plugins','disable','unified-notify'])])
            self.assertFalse(link.exists())
            self.assertTrue((backup/'previous-plugin').is_symlink())
            self.assertTrue((self.m.PROJECT/'__init__.py').is_file())
            self.assertEqual((home/'SOUL.md').read_text(),'Keep instructions')
            self.m.sync_native_plugin(home,'notes',False,backup,
                cli_runner=lambda *args:self.fail('already removed producer should not enable plugin'),
                config_reader=lambda home:{'plugins':{'disabled':['unified-notify']}})

    def test_existing_router_is_disabled_and_backed_up(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            home=Path(tmp)/'profile';(home/'plugins').mkdir(parents=True);backup=Path(tmp)/'backup';backup.mkdir()
            (home/'plugins/unified-notify').symlink_to(self.m.PROJECT,target_is_directory=True)
            calls=[]
            self.m.sync_native_plugin(home,'assistant-bot',False,backup,
                cli_runner=lambda name,args:calls.append((name,args)),config_reader=lambda home:{'plugins':{'enabled':['unified-notify']}})
            self.assertFalse((home/'plugins/unified-notify').exists())
            self.assertTrue((backup/'previous-plugin').is_symlink())
            self.assertEqual(calls,[('assistant-bot',['plugins','disable','unified-notify'])])

if __name__=='__main__':unittest.main()
