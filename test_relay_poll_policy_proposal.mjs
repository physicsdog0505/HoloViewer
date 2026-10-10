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
