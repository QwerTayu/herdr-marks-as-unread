import contextlib
import io
from pathlib import Path
import tempfile
import unittest
import tomllib
from install import configure, write_config

MARK = '$herdr_mark'


def rows_of(text):
    return tomllib.loads(text)['ui']['sidebar']['agents']['rows']


def leads(row):
    return isinstance(row[0], dict) and row[0]['token'] == MARK


class ConfigureTests(unittest.TestCase):
    def test_fresh_config_is_valid_and_idempotent(self):
        result = configure('')
        config = tomllib.loads(result)
        self.assertEqual(config['keys']['command'][0]['key'], 'prefix+m')
        rows = rows_of(result)
        self.assertEqual(rows[0][0], 'state_icon')
        self.assertEqual(rows[0][1]['token'], MARK)
        self.assertEqual(rows[0][2:], ['machine', 'workspace', 'tab'])
        self.assertEqual(rows[1], ['agent'])
        self.assertEqual(configure(result), result)

    def test_preserves_existing_rows_and_settings(self):
        source = '[theme]\nname="tokyo-night"\n[ui.sidebar.agents]\nrows = [\n ["state_text", {token="workspace", bold=true}],\n ["agent"]\n]\n[ui.toast]\ndelivery="herdr"\n'
        text = configure(source)
        result = tomllib.loads(text)
        before = tomllib.loads(source)
        self.assertEqual(result['theme'], before['theme'])
        self.assertEqual(result['ui']['toast'], before['ui']['toast'])
        original = before['ui']['sidebar']['agents']['rows']
        self.assertTrue(leads(rows_of(text)[0]))
        self.assertEqual(rows_of(text)[0][1:], original[0])
        self.assertEqual(rows_of(text)[1:], original[1:])
        self.assertEqual(configure(text), text)

    def test_marker_follows_state_icon_on_the_first_row_and_keeps_comments_and_rules(self):
        source = ('[ui.sidebar.agents]\nrows = [\n'
                  '  [{ token = "state_text", rules = [\n'
                  '     { starts_with = "working", fg = "#ffcc00" }, { equals = "[x] · #", hide = true } ] },\n'
                  '   "state_icon"], # first line\n'
                  '  [{ token = "agent", fg = "#6c7086" }],\n'
                  ']\n[ui.sidebar.agents.rows_by_agent]\nclaude = [["agent"]]\n')
        text = configure(source)
        rows = rows_of(text)
        self.assertEqual(rows[0][0]['rules'][1], {'equals': '[x] · #', 'hide': True})
        self.assertEqual(rows[0][1], 'state_icon')
        self.assertEqual(rows[0][2]['token'], MARK)
        self.assertEqual(len(rows[0]), 3)
        self.assertEqual(rows[1], [{'token': 'agent', 'fg': '#6c7086'}])
        self.assertIn('# first line', text)
        self.assertEqual(tomllib.loads(text)['ui']['sidebar']['agents']['rows_by_agent'], {'claude': [['agent']]})
        self.assertEqual(configure(text), text)

    def test_marker_follows_a_styled_state_icon_and_leads_rows_without_one(self):
        source = '[ui.sidebar.agents]\nrows = [["machine", { token = "state_icon", bold = true }, "workspace"], ["agent"]]\n'
        rows = rows_of(configure(source))
        self.assertEqual([r if isinstance(r, str) else r['token'] for r in rows[0]], ['machine', 'state_icon', MARK, 'workspace'])
        rows = rows_of(configure('[ui.sidebar.agents]\nrows = [["workspace"]]\n'))
        self.assertEqual([r if isinstance(r, str) else r['token'] for r in rows[0]], [MARK, 'workspace'])

    def test_rejects_rows_it_cannot_safely_rewrite(self):
        with self.assertRaisesRegex(ValueError, 'manually'):
            configure('[ui.sidebar]\nagents.rows = [["agent"]]\n')

    def test_migrates_old_marker_shortcut(self):
        source = '[[keys.command]]\nkey="prefix+alt+m"\ntype="plugin_action"\ncommand="local.herdr-marks.toggle"\n'
        result = configure(source)
        self.assertEqual(tomllib.loads(result)['keys']['command'][0]['key'], 'prefix+m')
        self.assertEqual(configure(result), result)

    def test_does_not_take_an_existing_shortcut(self):
        with self.assertRaisesRegex(ValueError, 'already bound'):
            configure('[[keys.command]]\nkey="prefix+m"\ncommand="other"\n')


class WriteConfigTests(unittest.TestCase):
    def test_writes_through_a_symlinked_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            dotfiles = Path(tmp, 'dotfiles')
            dotfiles.mkdir()
            target = dotfiles / 'config.toml'
            target.write_text('[theme]\nname="tokyo-night"\n')
            link = Path(tmp, 'config.toml')
            link.symlink_to(target)
            with contextlib.redirect_stdout(io.StringIO()):
                write_config(link, 'updated\n')
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), target.resolve())
            self.assertEqual(target.read_text(), 'updated\n')
            backups = list(dotfiles.glob('config.toml.marks-backup-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), '[theme]\nname="tokyo-night"\n')
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ['config.toml', 'dotfiles'])


if __name__ == '__main__':
    unittest.main()
