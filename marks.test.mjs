import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { toggle, clearFocused } from './marks.mjs';

for (const status of ['working', 'blocked', 'done', 'idle', 'unknown']) {
  for (const marked of [false, true]) {
    test(`${marked ? 'clear' : 'set'} marker while ${status}: only metadata is written`, () => {
      const agent = { pane_id: 'w1:p1', agent_status: status,
        tokens: { other: 'keep', ...(marked ? { herdr_mark: 'unread' } : {}) } };
      const before = structuredClone(agent);
      const calls = [];
      toggle({ env: { HERDR_ENV: '1', HERDR_PANE_ID: 'wrong',
        HERDR_PLUGIN_CONTEXT_JSON: '{"focused_pane_id":"w1:p1"}' }, run(args) {
        calls.push(args);
        return args[0] === 'agent' ? { agent } : { type: 'ok' };
      }});
      assert.deepEqual(agent, before);
      assert.deepEqual(calls, [['agent', 'get', 'w1:p1'],
        ['pane', 'report-metadata', 'w1:p1', '--source', 'plugin:herdr-marks',
          ...(marked ? ['--clear-token', 'herdr_mark'] : ['--token', 'herdr_mark=unread'])]]);
    });
  }
}

test('rejects missing environment, missing targets, and unavailable agents', () => {
  assert.throws(() => toggle({ env: {} }), /inside Herdr/);
  assert.throws(() => toggle({ env: { HERDR_ENV: '1' } }), /No target/);
  assert.throws(() => toggle({ env: { HERDR_ENV: '1' }, target: 'w1:p1',
    run() { throw new Error('agent unavailable'); } }), /unavailable/);
});

for (const marked of [true, false]) {
  test(`focus clears only the event target; marked=${marked}`, () => {
    const calls = [];
    const pane = { pane_id: 'w2:p3', agent_status: 'done', tokens: { other: 'keep', ...(marked ? { herdr_mark: 'unread' } : {}) } };
    const before = structuredClone(pane);
    clearFocused({ env: { HERDR_ENV: '1', HERDR_PANE_ID: 'wrong',
      HERDR_PLUGIN_EVENT_JSON: JSON.stringify({ event: 'pane.focused', data: { type: 'pane_focused', pane_id: 'w2:p3' } }) },
      run(args) { calls.push(args); return { pane: calls.length > 2 ? { ...pane, tokens: {} } : pane }; } });
    assert.deepEqual(calls, [['pane', 'get', 'w2:p3'], ...(marked ? [
      ['pane', 'report-metadata', 'w2:p3', '--source', 'plugin:herdr-marks', '--clear-token', 'herdr_mark'],
      ['pane', 'get', 'w2:p3'],
    ] : [])]);
    assert.deepEqual(pane, before);
  });
}

test('missing or unrelated events cannot clear an arbitrary pane', () => {
  assert.throws(() => clearFocused({ env: { HERDR_ENV: '1', HERDR_PANE_ID: 'w1:p1' } }), /Expected/);
  assert.throws(() => clearFocused({ env: { HERDR_ENV: '1', HERDR_PLUGIN_EVENT_JSON:
    JSON.stringify({ event: 'pane.updated', data: { type: 'pane_focused', pane_id: 'w1:p1' } }) } }), /Expected/);
});

for (const kind of ['tab', 'workspace']) {
  for (const matches of [true, false]) {
    test(`${kind} return clears viewed pane only; current matches=${matches}`, () => {
      const calls = [];
      const data = { type: `${kind}_focused`, workspace_id: 'w2',
        ...(kind === 'tab' ? { tab_id: 'w2:t1' } : {}) };
      clearFocused({ env: { HERDR_ENV: '1', HERDR_PANE_ID: 'wrong',
        HERDR_PLUGIN_EVENT_JSON: JSON.stringify({ event: `${kind}.focused`, data }) },
        run(args) {
          calls.push(args);
          return { pane: { pane_id: 'w2:p3', workspace_id: matches ? 'w2' : 'w3',
            tab_id: 'w2:t1', tokens: { ...(calls.length < 3 ? { herdr_mark: 'unread' } : {}), unrelated: 'keep' } } };
        } });
      assert.deepEqual(calls, [['pane', 'current'], ...(matches ? [
        ['pane', 'report-metadata', 'w2:p3', '--source', 'plugin:herdr-marks', '--clear-token', 'herdr_mark'],
        ['pane', 'get', 'w2:p3'],
      ] : [])]);
    });
  }
}

test('supports raw hook data with event kind supplied in environment', () => {
  const calls = [];
  clearFocused({ env: { HERDR_ENV: '1', HERDR_PLUGIN_EVENT: 'pane.focused',
    HERDR_PLUGIN_EVENT_JSON: '{"type":"pane_focused","pane_id":"w1:p1"}' },
    run(args) { calls.push(args); return { pane: { pane_id: 'w1:p1', tokens: calls.length < 3 ? { herdr_mark: 'unread' } : {} } }; } });
  assert.equal(calls[1][2], 'w1:p1');
});

test('reports failed verification when Herdr retains the token', () => {
  assert.throws(() => clearFocused({ env: { HERDR_ENV: '1', HERDR_PLUGIN_EVENT: 'pane.focused',
    HERDR_PLUGIN_EVENT_JSON: '{"type":"pane_focused","pane_id":"w1:p1"}' },
    run() { return { pane: { pane_id: 'w1:p1', tokens: { herdr_mark: 'unread' } } }; } }), /still reports/);
});

test('accepts the actual live Herdr envelope with snake_case event kind', () => {
  const calls = [];
  const result = clearFocused({ env: { HERDR_ENV: '1', HERDR_PLUGIN_EVENT: 'workspace.focused',
    HERDR_PLUGIN_EVENT_JSON: '{"event":"workspace_focused","data":{"type":"workspace_focused","workspace_id":"w5"}}' },
    run(args) {
      calls.push(args);
      return { pane: { pane_id: 'w5:p1', workspace_id: 'w5',
        tokens: calls.length < 3 ? { herdr_mark: 'unread' } : {} } };
    } });
  assert.deepEqual(result, { outcome: 'cleared', pane_id: 'w5:p1', marker_present: false });
  assert.equal(calls.length, 3);
});

test('CLI integration: silent metadata success and readback work through real subprocesses', () => {
  const dir = mkdtempSync(join(tmpdir(), 'herdr-marks-test-'));
  try {
    const binary = join(dir, 'herdr');
    const state = join(dir, 'pane.json');
    writeFileSync(state, JSON.stringify({ pane_id: 'w5:p1', workspace_id: 'w5',
      agent_status: 'done', tokens: { herdr_mark: 'unread', other: 'keep' } }));
    writeFileSync(binary, `#!/usr/bin/env node
const fs = require('node:fs');
const path = process.env.MARKS_TEST_STATE;
const pane = JSON.parse(fs.readFileSync(path, 'utf8'));
const args = process.argv.slice(2);
if (args[1] === 'report-metadata') {
  if (args.includes('--clear-token')) delete pane.tokens.herdr_mark;
  else pane.tokens.herdr_mark = 'unread';
  fs.writeFileSync(path, JSON.stringify(pane));
} else console.log(JSON.stringify({ result: args[0] === 'agent' ? {agent:pane} : {pane} }));
`, { mode: 0o755 });
    const env = { ...process.env, HERDR_ENV: '1', HERDR_BIN_PATH: binary, MARKS_TEST_STATE: state,
      HERDR_PLUGIN_EVENT: 'workspace.focused', HERDR_PLUGIN_EVENT_JSON:
        '{"event":"workspace_focused","data":{"type":"workspace_focused","workspace_id":"w5"}}' };
    assert.equal(clearFocused({ env }).outcome, 'cleared');
    assert.deepEqual(JSON.parse(readFileSync(state)).tokens, { other: 'keep' });
    toggle({ env, target: 'w5:p1' });
    const after = JSON.parse(readFileSync(state));
    assert.equal(after.tokens.herdr_mark, 'unread');
    assert.equal(after.agent_status, 'done');
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
