import unittest
from unittest.mock import patch
import cli

class CheckCLITests(unittest.TestCase):
    def test_check_calls_profile_diagnostics(self):
        with patch('sys.argv', ['cli.py', 'check']), patch('diagnostics.telegram_status', return_value={'status': 'connected'}) as check, patch('onboard.profiles_plan', return_value=[{'name':'cron', 'home':'/fake/cron', 'native_plugin':True}]), patch('sys.stdout'):
            self.assertEqual(cli.main(), 0)
            check.assert_called_once_with('/fake/cron')

if __name__ == '__main__':
    unittest.main()
