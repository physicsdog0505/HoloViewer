// Execute with node --experimental-default-type=module --test ptt_offline/test_d1_worker_freshness.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { publicPttFreshness } from './d1_worker_routes.js';

const now = Date.parse('2026-10-15T08:00:00Z');

test('valid checked_at within TTL is fresh', () => {
  assert.equal(publicPttFreshness('2026-10-15T07:59:50Z', now), 'fresh');
});

test('known old timestamp is stale', () => {
  assert.equal(publicPttFreshness('2026-10-15T07:00:00Z', now), 'stale');
});

test('malformed, missing, future timestamps fail closed', () => {
  for (const timestamp of ['not-a-date', null,
                           '2026-10-15T08:00:01Z']) {
    assert.equal(publicPttFreshness(timestamp, now), 'unknown');
  }
});
