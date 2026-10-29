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
        self.assertEqual(rows[0], ['state_icon', 'machine', 'workspace', 'tab'])
        self.assertTrue(leads(rows[1]))
        self.assertEqual(rows[1][1:], ['agent'])
        self.assertEqual(configure(result), result)

    def test_preserves_existing_rows_and_settings(self):
        source = '[theme]\nname="tokyo-night"\n[ui.sidebar.agents]\nrows = [\n ["state_text", {token="workspace", bold=true}],\n ["agent"]\n]\n[ui.toast]\ndelivery="herdr"\n'
        text = configure(source)
        result = tomllib.loads(text)
        before = tomllib.loads(source)
        self.assertEqual(result['theme'], before['theme'])
        self.assertEqual(result['ui']['toast'], before['ui']['toast'])
        original = before['ui']['sidebar']['agents']['rows']
        self.assertEqual(rows_of(text)[0], original[0])
        self.assertTrue(leads(rows_of(text)[1]))
        self.assertEqual(rows_of(text)[1][1:], original[1])
        self.assertEqual(configure(text), text)

    def test_marker_leads_the_second_row_and_keeps_comments_and_rules(self):
        source = ('[ui.sidebar.agents]\nrows = [\n'
                  '  ["state_icon", "workspace"], # first line\n'
                  '  [{ token = "state_text", rules = [\n'
                  '     { starts_with = "working", fg = "#ffcc00" }, { equals = "[x] · #", hide = true } ] },\n'
                  '   { token = "agent", fg = "#6c7086" }],\n'
                  ']\n[ui.sidebar.agents.rows_by_agent]\nclaude = [["agent"]]\n')
        text = configure(source)
        rows = rows_of(text)
        self.assertEqual(rows[0], ['state_icon', 'workspace'])
        self.assertTrue(leads(rows[1]))
        self.assertEqual(rows[1][1]['rules'][1], {'equals': '[x] · #', 'hide': True})
        self.assertEqual(rows[1][2], {'token': 'agent', 'fg': '#6c7086'})
        self.assertIn('# first line', text)
        self.assertEqual(tomllib.loads(text)['ui']['sidebar']['agents']['rows_by_agent'], {'claude': [['agent']]})
        self.assertEqual(configure(text), text)

    def test_single_row_layouts_get_the_marker_first(self):
        rows = rows_of(configure('[ui.sidebar.agents]\nrows = [["state_icon", "workspace"]]\n'))
        self.assertEqual([r if isinstance(r, str) else r['token'] for r in rows[0]], [MARK, 'state_icon', 'workspace'])
        rows = rows_of(configure('[ui.sidebar.agents]\nrows = [["workspace"], []]\n'))
        self.assertEqual(rows[1][0]['token'], MARK)

    def test_moves_a_first_line_marker_from_an_older_install_to_the_detail_line(self):
        source = ('[ui.sidebar.agents]\nrows = [\n'
                  '  [{ token = "$herdr_mark", fg = "#9ece6a", bold = true, dim = false }, "state_icon", # name\n'
                  '   { token = "workspace", bold = true }],\n'
                  '  [{ token = "state_text", rules = [{ equals = "a, b", fg = "#fff" }] }, "agent"],\n'
                  ']\n')
        text = configure(source)
        rows = rows_of(text)
        self.assertEqual(rows[0], ['state_icon', {'token': 'workspace', 'bold': True}])
        self.assertEqual(rows[1][0], {'token': MARK, 'fg': '#9ece6a', 'bold': True, 'dim': False})
        self.assertEqual(rows[1][1:], [{'token': 'state_text', 'rules': [{'equals': 'a, b', 'fg': '#fff'}]}, 'agent'])
        self.assertIn('# name', text)
        self.assertEqual(configure(text), text)
        trailing = '[ui.sidebar.agents]\nrows = [["state_icon", "workspace", "$herdr_mark"], ["agent"], ["$herdr_mark"]]\n'
        rows = rows_of(configure(trailing))
        style = {'token': MARK, 'fg': '#f7768e', 'bold': True, 'dim': False}
        self.assertEqual(rows, [['state_icon', 'workspace'], [style, 'agent'], []])
        self.assertEqual(rows_of(configure('[ui.sidebar.agents]\nrows = [["$herdr_mark", "workspace"]]\n'))[0][0], '$herdr_mark')

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
