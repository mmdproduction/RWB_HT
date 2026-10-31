import assert from 'node:assert/strict';
import { test } from 'node:test';
import { isActive, shouldPoll, safeExternalUrl, progressPercent, nextLogCursor } from '../src/run-state.ts';

test('polls queued and running jobs, stops all terminal states', () => {
  assert.equal(isActive('queued'), true);
  assert.equal(isActive('running'), true);
  for (const state of ['succeeded', 'failed', 'blocked', 'interrupted']) assert.equal(isActive(state), false);
  assert.equal(shouldPoll([{ status: 'failed' }, { status: 'queued' }]), true);
  assert.equal(shouldPoll([{ status: 'succeeded' }]), false);
});
test('external result links accept only HTTP and HTTPS', () => {
  assert.equal(safeExternalUrl('javascript:alert(1)'), null);
  assert.equal(safeExternalUrl('data:text/html,test'), null);
  assert.equal(safeExternalUrl('/api/runs'), null);
  assert.equal(safeExternalUrl('http://127.0.0.1:8091'), 'http://127.0.0.1:8091/');
});
test('pending and skipped stages do not count as passed', () => {
  assert.equal(progressPercent([{ status: 'passed' }, { status: 'not_run' }, { status: 'pending' }, { status: 'running' }]), 25);
  assert.equal(progressPercent([]), 0);
});
test('log cursor advances monotonically and includes final partial page', () => {
  assert.equal(nextLogCursor(50, { nextCursor: 54, items: [{ cursor: 54 }] }), 54);
  assert.equal(nextLogCursor(54, { nextCursor: 54, items: [] }), 54);
  assert.equal(nextLogCursor(54, { nextCursor: 2, items: [] }), 54);
});
