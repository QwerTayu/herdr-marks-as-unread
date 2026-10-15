import unittest
import tomllib
from install import configure


class ConfigureTests(unittest.TestCase):
    def test_fresh_config_is_valid_and_idempotent(self):
        result = configure('')
        config = tomllib.loads(result)
        self.assertEqual(config['keys']['command'][0]['key'], 'prefix+m')
        self.assertEqual(config['ui']['sidebar']['agents']['rows'][0][0]['token'], '$herdr_mark')
        self.assertEqual(configure(result), result)

    def test_preserves_existing_rows_and_settings(self):
        source = '[theme]\nname="tokyo-night"\n[ui.sidebar.agents]\nrows = [\n ["state_text", {token="workspace", bold=true}],\n ["agent"]\n]\n[ui.toast]\ndelivery="herdr"\n'
        result = tomllib.loads(configure(source))
        before = tomllib.loads(source)
        self.assertEqual(result['theme'], before['theme'])
        self.assertEqual(result['ui']['toast'], before['ui']['toast'])
        self.assertEqual(result['ui']['sidebar']['agents']['rows'][0][1:], before['ui']['sidebar']['agents']['rows'][0])

    def test_migrates_old_marker_shortcut(self):
        source = '[[keys.command]]\nkey="prefix+alt+m"\ntype="plugin_action"\ncommand="local.herdr-marks.toggle"\n'
        result = configure(source)
        self.assertEqual(tomllib.loads(result)['keys']['command'][0]['key'], 'prefix+m')
        self.assertEqual(configure(result), result)

    def test_does_not_take_an_existing_shortcut(self):
        with self.assertRaisesRegex(ValueError, 'already bound'):
            configure('[[keys.command]]\nkey="prefix+m"\ncommand="other"\n')


if __name__ == '__main__':
    unittest.main()
