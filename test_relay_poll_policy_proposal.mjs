// Offline-only proposed scheduler specification; not imported by production Reader.
import assert from "node:assert/strict";
import test from "node:test";

const weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const schedule = Object.freeze({
  Mon: [18 * 60, 22 * 60], Tue: [18 * 60, 22 * 60],
  Wed: [18 * 60, 22 * 60], Thu: [18 * 60, 22 * 60],
  Fri: [18 * 60, 22 * 60], Sat: [16 * 60, 22 * 60],
  Sun: [16 * 60, 22 * 60],
});
const format = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Taipei", weekday: "short", hour: "2-digit",
  minute: "2-digit", hourCycle: "h23",
});

function taipeiParts(date) {
  const fields = Object.fromEntries(format.formatToParts(date)
    .filter(p => ["weekday", "hour", "minute"].includes(p.type))
    .map(p => [p.type, p.value]));
  assert(weekdays.includes(fields.weekday));
  return {day: fields.weekday, minute: Number(fields.hour) * 60 + Number(fields.minute)};
}

// A temporary override must be explicitly activated; no persistent browser/admin state.
function proposalInterval(now, {visible = true, override = null} = {}) {
  if (!visible) return null;
  if (override && now.getTime() >= override.startMs &&
      now.getTime() < override.endMs) return override.seconds;
  const {day, minute} = taipeiParts(now);
  const [start, end] = schedule[day];
  return minute >= start && minute < end ? 10 : 120;
}

function override60Minutes(start) {
  return {startMs: start.getTime(), endMs: start.getTime() + 60 * 60 * 1000, seconds: 10};
}

function volume(peakHours, viewers = 10) {
  return viewers * (peakHours * 3600 / 10 + (24 - peakHours) * 3600 / 120);
}

test("weekly 10-second windows apply independently to all seven Taipei weekdays", () => {
  // 2026-10-12 is Monday; 18:00 Taipei = 10:00Z; 16:00 Taipei = 08:00Z.
  for (let index = 0; index < 7; index++) {
    const date = new Date(Date.UTC(2026, 9, 12 + index, 0, 0));
    const expectedStart = index < 5 ? 10 : 8;
    const at = hour => new Date(date.getTime() + hour * 3600000);
    assert.equal(proposalInterval(at(expectedStart - 1)), 120, `day ${index} before start`);
    assert.equal(proposalInterval(at(expectedStart)), 10, `day ${index} start inclusive`);
    assert.equal(proposalInterval(at(13)), 10, `day ${index} at 21:00 Taipei`);
    assert.equal(proposalInterval(at(14)), 120, `day ${index} end exclusive`);
  }
});

test("weekend 16:00 applies where weekday 16:00 remains offpeak", () => {
  assert.equal(proposalInterval(new Date("2026-10-12T08:00:00Z")), 120);
  assert.equal(proposalInterval(new Date("2026-10-17T08:00:00Z")), 10);
  assert.equal(proposalInterval(new Date("2026-10-18T08:00:00Z")), 10);
});

test("temporary 60-minute 10s override starts explicitly and expires back to weekday schedule", () => {
  const start = new Date("2026-10-12T06:30:00Z"); // Monday 14:30
  const o = override60Minutes(start);
  assert.equal(proposalInterval(new Date(start.getTime()-1000), {override:o}), 120);
  assert.equal(proposalInterval(start, {override:o}), 10);
  assert.equal(proposalInterval(new Date(start.getTime()+59*60000), {override:o}), 10);
  assert.equal(proposalInterval(new Date(start.getTime()+60*60000), {override:o}), 120);
  assert.equal(proposalInterval(new Date(start.getTime()+60*60000)), 120);
});

test("override crossing midnight respects expiry and next day's own rule", () => {
  const start = new Date("2026-10-16T15:30:00Z"); // Friday 23:30 Taipei
  const o = override60Minutes(start);
  assert.equal(proposalInterval(new Date("2026-10-16T16:00:00Z"), {override:o}), 10);
  assert.equal(proposalInterval(new Date("2026-10-16T16:30:00Z"), {override:o}), 120);
  assert.equal(proposalInterval(new Date("2026-10-17T08:00:00Z"), {override:o}), 10);
});

test("background tabs pause GET scheduling even during an active override", () => {
  const now = new Date("2026-10-17T08:00:00Z");
  assert.equal(proposalInterval(now, {visible:false,override:override60Minutes(now)}), null);
  assert.equal(proposalInterval(now, {visible:true}), 10);
});

test("request math for 10 viewers and weekday/weekend schedule", () => {
  assert.equal(volume(4), 20400);
  assert.equal(volume(6), 27000);
  assert.equal(5*volume(4)+2*volume(6), 156000);
  assert.equal(7*10*24*3600/5, 1209600);
  assert.equal((1-156000/1209600)*100 > 87, true);
  assert.equal(volume(4,1), 2040);
  assert.equal(volume(6,100), 270000);
});


// A long off-peak sleep must not skip the start of a 10-second peak window.
// Compute the next schedule boundary independently of the reader's current timer.
function nextBoundaryDelayMs(now) {
  const current = proposalInterval(now);
  const base = now.getTime();
  // Only two boundaries per day; minute-stepping is deterministic in this
  // synthetic specification, NOT proposed as production timer implementation.
  for (let minutes = 1; minutes <= 24 * 60 + 1; minutes++) {
    const candidate = new Date(base + minutes * 60000);
    if (proposalInterval(candidate) !== current) {
      return minutes * 60000;
    }
  }
  throw new Error("next boundary missing");
}

function proposedWaitMs(now, {visible = true, override = null, failures = 0, retryAfterMs = 0} = {}) {
  const interval = proposalInterval(now, {visible, override});
  if (interval === null) return null;
  const adaptiveMs = interval * 1000;
  const boundary = nextBoundaryDelayMs(now);
  const overrideExpiry = override && now.getTime() < override.endMs
    ? Math.max(1, override.endMs - now.getTime()) : Infinity;
  // Avoid retry storms; a server Retry-After may further extend this delay.
  const backoffMs = failures ? Math.min(300000, 10000 * 2 ** Math.min(failures - 1, 5)) : 0;
  return Math.max(backoffMs, retryAfterMs, Math.min(adaptiveMs, boundary, overrideExpiry));
}

test("timer clamps offpeak wait at approaching weekday and weekend boundaries", () => {
  assert.equal(proposedWaitMs(new Date("2026-10-12T09:59:00Z")), 60000);
  assert.equal(proposedWaitMs(new Date("2026-10-17T07:59:00Z")), 60000);
  assert.equal(proposedWaitMs(new Date("2026-10-12T13:59:30Z")), 10000);
  assert.equal(proposedWaitMs(new Date("2026-10-12T14:00:00Z")), 120000);
});

test("override timer wakes at expiry even when ordinary interval is longer", () => {
  const start = new Date("2026-10-12T06:00:00Z");
  const override = override60Minutes(start);
  assert.equal(proposedWaitMs(new Date("2026-10-12T06:59:55Z"), {override}), 5000);
  assert.equal(proposedWaitMs(new Date("2026-10-12T07:00:00Z"), {override}), 120000);
});

test("429/5xx retry policy is bounded and never retries tighter than server advice", () => {
  const offpeak = new Date("2026-10-12T05:00:00Z");
  assert.equal(proposedWaitMs(offpeak, {failures:1}), 120000);
  assert.equal(proposedWaitMs(offpeak, {failures:7}), 300000);
  assert.equal(proposedWaitMs(offpeak, {failures:1,retryAfterMs:600000}), 600000);
  assert.equal(proposedWaitMs(offpeak, {visible:false,failures:7}), null);
});

test("viewer and extra-article counts scale GETs without equating them to D1 writes", () => {
  for (const users of [10,50,100]) {
    assert.equal(volume(4,users), 2040 * users);
    assert.equal(volume(6,users), 2700 * users);
    assert.equal(5*volume(4,users)+2*volume(6,users), 15600 * users);
  }
  // One extra simultaneously polled AID doubles GETs without necessarily
  // writing anything. Cache effectiveness and D1 read rows are not inferred.
  assert.equal(2 * (5*volume(4,10)+2*volume(6,10)), 312000);
});
