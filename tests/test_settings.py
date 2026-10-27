import unittest
from pathlib import Path
import settings
from hermes_cli.plugins_settings import plugin_settings_fields

class SettingsTests(unittest.TestCase):
    def test_native_ui_declares_every_operational_setting(self):
        fields = plugin_settings_fields('unified-notify', Path(__file__).resolve().parents[1])
        self.assertEqual({f['key'] for f in fields}, set(settings.DEFAULTS))
        self.assertNotIn('role', {f['key'] for f in fields})
        self.assertNotIn('api_key', {f['key'] for f in fields})

    def test_configuration_validation_fails_closed(self):
        for value in ({'batch_size':True}, {'spacing_seconds':'bad'}):
            with self.subTest(value=value), self.assertRaises(ValueError):settings.validate(value)
        result=settings.validate({'role':'router','channel_id':-123})
        self.assertNotIn('role',result)
        with self.assertRaises(ValueError):settings.validate({}, transport=True)
        for role in ('producer','router','transport'):
            self.assertNotIn('role',settings.validate({'role':role}))
        self.assertEqual(result['db_path'],result['root_home']/'data/unified-notify.sqlite3')
