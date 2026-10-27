#!/usr/bin/env python3
"""Link the plugin and install a marker token + shortcut, preserving other settings."""
import datetime
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parent
ACTION = 'local.herdr-marks.toggle'
STYLE = '{ token = "$herdr_mark", fg = "#9ece6a", bold = true, dim = false }'


def row_starts(text, start):
    """Yield offsets just inside each top-level row of the TOML array opening at text[start]."""
    depth = braces = 0
    quote = None
    i = start
    while i < len(text):
        c = text[i]
        if quote:
            if c == '\\' and quote == '"': i += 1
            elif c == quote: quote = None
        elif c in '"\'': quote = c
        elif c == '#':
            i = text.find('\n', i)
            if i == -1: return
        elif c == '{': braces += 1
        elif c == '}': braces -= 1
        elif c == '[':
            depth += 1
            if depth == 2 and braces == 0: yield i + 1
        elif c == ']':
            depth -= 1
            if depth == 0: return
        i += 1


def configure(text):
    data = tomllib.loads(text)
    agents = data.get('ui', {}).get('sidebar', {}).get('agents', {})
    token = lambda item: item.get('token') if isinstance(item, dict) else item
    rows = agents.get('rows', [])
    # The badge leads the second (detail) line so the name line stays untouched; a
    # single-line layout gets it first. Herdr always joins it to the next token with " · ".
    default_rows = '[["state_icon", "machine", "workspace", "tab"], [' + STYLE + ', "agent"]]'
    if 'rows' in agents and not any(token(item) == '$herdr_mark' for row in rows for item in row):
        # Insert directly in the existing TOML array, retaining styles and comments.
        section = re.search(r'(?m)^\[ui\.sidebar\.agents\][ \t]*(?:#.*)?$', text)
        body_start = section.end() if section else len(text)
        end = re.search(r'(?m)^\[', text[body_start:])
        limit = body_start + end.start() if end else len(text)
        match = re.search(r'(?m)^rows\s*=\s*\[', text[body_start:limit])
        starts = list(row_starts(text, body_start + match.end() - 1)) if match else []
        if len(starts) != len(rows) or not starts:
            raise ValueError('Unrecognized agent rows syntax; configure $herdr_mark manually.')
        pos = starts[1] if len(starts) > 1 else starts[0]
        comma = '' if text[pos:].lstrip().startswith(']') else ', '
        text = text[:pos] + STYLE + comma + text[pos:]
    elif 'rows' not in agents:
        section = re.search(r'(?m)^\[ui\.sidebar\.agents\][ \t]*(?:#.*)?$', text)
        if section:
            end = re.search(r'(?m)^\[', text[section.end():])
            limit = section.end() + end.start() if end else len(text)
            text = text[:limit] + '\nrows = ' + default_rows + '\n' + text[limit:]
        else:
            text += '\n[ui.sidebar.agents]\nrows = ' + default_rows + '\n'
    commands = data.get('keys', {}).get('command', [])
    is_marker = lambda c: c.get('type') == 'plugin_action' and c.get('command') == ACTION
    def has_key(value):
        if isinstance(value, str): return value.lower() == 'prefix+m'
        if isinstance(value, list): return any(has_key(v) for v in value)
        if isinstance(value, dict): return any(has_key(v) for v in value.values())
        return False
    other_keys = {k: v for k, v in data.get('keys', {}).items() if k != 'command'}
    other_keys['command'] = [c for c in commands if not is_marker(c)]
    if has_key(other_keys):
        raise ValueError('prefix+m is already bound; choose a free shortcut manually.')
    if any(is_marker(c) for c in commands):
        # Migrate only this plugin's command blocks, leaving other bindings intact.
        pattern = r'(?ms)^\[\[keys\.command\]\][ \t]*(?:#.*)?$.*?(?=^\[|\Z)'
        def migrate(match):
            block = match.group(0)
            entry = tomllib.loads(block)['keys']['command'][0]
            if not is_marker(entry): return block
            changed, count = re.subn(r'(?m)^key[ \t]*=.*$', 'key = "prefix+m"', block)
            if count != 1: raise ValueError('Unrecognized marker key syntax.')
            return changed
        text = re.sub(pattern, migrate, text)
        migrated = [c for c in tomllib.loads(text)['keys']['command'] if is_marker(c)]
        if any(c.get('key') != 'prefix+m' for c in migrated):
            raise ValueError('Could not safely update the marker shortcut.')
    else:
        text += '\n[[keys.command]]\nkey = "prefix+m"\ntype = "plugin_action"\ncommand = "' + ACTION + '"\ndescription = "Toggle agent marker"\n'
    tomllib.loads(text)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configure-only', action='store_true',
                        help='Configure an installed plugin without replacing its GitHub registration.')
    args = parser.parse_args()
    if os.environ.get('HERDR_ENV') != '1':
        raise SystemExit('Run this installer from a terminal inside Herdr.')
    herdr = os.environ.get('HERDR_BIN_PATH') or shutil.which('herdr')
    if not herdr or not shutil.which('node'):
        raise SystemExit('Herdr and Node.js are required.')
    config = Path(os.environ.get('HERDR_CONFIG_PATH', str(Path.home() / '.config/herdr/config.toml'))).expanduser()
    before = config.read_text() if config.exists() else ''
    after = configure(before)
    if not args.configure_only:
        subprocess.run([herdr, 'plugin', 'link', str(ROOT)], check=True)
    if after != before:
        config.parent.mkdir(parents=True, exist_ok=True)
        if config.exists():
            backup = config.with_name(config.name + '.marks-backup-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            shutil.copy2(config, backup)
            print(f'Config backup: {backup}')
        with tempfile.NamedTemporaryFile(mode='w', dir=config.parent, delete=False) as f:
            f.write(after)
            temp = Path(f.name)
        if config.exists(): shutil.copymode(config, temp)
        temp.replace(config)
    subprocess.run([herdr, 'server', 'reload-config'], check=True)
    subprocess.run([herdr, 'plugin', 'action', 'list', '--plugin', 'local.herdr-marks'], check=True)
    print('Installed. Focus an agent, press Ctrl+B, then M (or your configured prefix, then M).')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'Herdr Marks installation failed: {error}') from None
