import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

export const TOKEN = 'herdr_mark';
// A word, not a glyph: it leads the dim second sidebar line as one more status fact.
export const MARK = 'unread';

function client(env, run) {
  if (env.HERDR_ENV !== '1') throw new Error('Run this command inside Herdr.');
  return run || ((args) => {
    const result = spawnSync(env.HERDR_BIN_PATH || 'herdr', args, {
      env, encoding: 'utf8', timeout: 10000,
    });
    if (result.error) throw result.error;
    if (result.status !== 0) throw new Error(result.stderr.trim() || 'Herdr command failed.');
    const output = result.stdout.trim();
    // report-metadata is a silent CLI command on Herdr 0.9.3.
    if (!output && args[0] === 'pane' && args[1] === 'report-metadata') return { type: 'ok' };
    if (!output) throw new Error(`No JSON response from herdr ${args.slice(0, 2).join(' ')}.`);
    const response = JSON.parse(output);
    if (response.error) throw new Error(response.error.message);
    return response.result;
  });
}

export function toggle({ env = process.env, target, run } = {}) {
  const call = client(env, run);
  const context = JSON.parse(env.HERDR_PLUGIN_CONTEXT_JSON || '{}');
  // Plugin context identifies the pane selected when the action was invoked.
  const pane = target || context.focused_pane_id || env.HERDR_PANE_ID;
  if (!pane) throw new Error('No target pane. Focus an agent and try again.');
  // agent.get rejects panes without a live agent; reading does not mark done as seen.
  const { agent } = call(['agent', 'get', pane]);
  if (!agent || agent.pane_id !== pane) throw new Error('The target no longer contains that agent.');
  const marked = Boolean(agent.tokens?.[TOKEN]);
  call(['pane', 'report-metadata', pane, '--source', 'plugin:herdr-marks',
    ...(marked ? ['--clear-token', TOKEN] : ['--token', `${TOKEN}=${MARK}`])]);
  return `${marked ? 'Unmarked' : 'Marked'} ${pane}`;
}

export function clearFocused({ env = process.env, run } = {}) {
  const event = JSON.parse(env.HERDR_PLUGIN_EVENT_JSON || '{}');
  // Hook names are dotted, but the event envelope uses snake_case kinds.
  const kind = env.HERDR_PLUGIN_EVENT || ({
    pane_focused: 'pane.focused', tab_focused: 'tab.focused', workspace_focused: 'workspace.focused',
  }[event.event] || event.event);
  const data = event.data || event;
  const types = { 'pane.focused': 'pane_focused', 'tab.focused': 'tab_focused', 'workspace.focused': 'workspace_focused' };
  if (!types[kind] || data.type !== types[kind]) {
    throw new Error('Expected a pane, tab, or workspace focus event.');
  }
  const call = client(env, run);
  let current;
  if (kind === 'pane.focused') {
    if (!data.pane_id) throw new Error('Focus event is missing its pane ID.');
    ({ pane: current } = call(['pane', 'get', data.pane_id]));
  } else {
    // Returning to an already-focused pane via its tab/workspace need not
    // emit pane.focused. Resolve the UI focus, not this process's caller pane.
    if (!data.workspace_id || (kind === 'tab.focused' && !data.tab_id)) {
      throw new Error('Focus event is missing its workspace or tab ID.');
    }
    ({ pane: current } = call(['pane', 'current']));
    // Delayed hooks must not clear an unrelated workspace/tab's marker.
    if (current?.workspace_id !== data.workspace_id ||
        (data.tab_id && current?.tab_id !== data.tab_id)) return { outcome: 'stale-focus' };
  }
  // A focus event also occurs for shells. Avoid writes to unmarked panes.
  if (current?.pane_id && current.tokens?.[TOKEN]) {
    call(['pane', 'report-metadata', current.pane_id, '--source', 'plugin:herdr-marks', '--clear-token', TOKEN]);
    // Read back from Herdr, so the diagnostic records the actual stored token.
    const { pane: after } = call(['pane', 'get', current.pane_id]);
    if (after?.tokens?.[TOKEN]) throw new Error('Herdr still reports the marker after clearing it.');
    return { outcome: 'cleared', pane_id: current.pane_id, marker_present: false };
  }
  return { outcome: 'already-unmarked', pane_id: current?.pane_id };
}

function recordFocus(result) {
  const directory = process.env.HERDR_PLUGIN_STATE_DIR;
  if (!directory) return;
  mkdirSync(directory, { recursive: true });
  writeFileSync(join(directory, 'last-focus.json'), JSON.stringify({
    time: new Date().toISOString(), event: process.env.HERDR_PLUGIN_EVENT,
    payload: JSON.parse(process.env.HERDR_PLUGIN_EVENT_JSON || '{}'), ...result,
  }, null, 2) + '\n');
  if (result.outcome === 'cleared') {
    writeFileSync(join(directory, 'last-cleared.json'), JSON.stringify({
      time: new Date().toISOString(), event: process.env.HERDR_PLUGIN_EVENT, ...result,
    }, null, 2) + '\n');
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    if (process.argv[2] === 'clear-focused') recordFocus(clearFocused());
    else if (process.argv[2] === 'toggle') console.log(toggle({ target: process.argv[3] }));
    else throw new Error('Usage: node marks.mjs toggle [pane-id] | clear-focused');
  } catch (error) {
    if (process.argv[2] === 'clear-focused') {
      try { recordFocus({ outcome: 'error', error: error.message }); } catch {}
    }
    console.error(`Herdr Marks: ${error.message}`);
    process.exitCode = 1;
  }
}
