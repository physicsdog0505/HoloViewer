// Offline-only synthetic proposal tests. NOT imported by production Reader.
// 18:00-00:00 Asia/Taipei is an illustrative six-hour window, NOT an approved schedule.
import assert from "node:assert/strict";
import test from "node:test";

const PEAK_SECONDS = 10;
const OFFPEAK_SECONDS = 120;
const peakStart = 18 * 60; // example only
const peakDuration = 6 * 60;
const taipei = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Taipei", hour: "2-digit", minute: "2-digit",
  hourCycle: "h23",
});

function getTaipeiMinute(date) {
  const parts = Object.fromEntries(
    taipei.formatToParts(date).filter(p => p.type === "hour" || p.type === "minute")
      .map(p => [p.type, Number(p.value)])
  );
  return parts.hour * 60 + parts.minute;
}

function proposalInterval(date, {visible = true} = {}) {
  if (!visible) return null; // paused in background, wake requires revalidation
  const minute = getTaipeiMinute(date);
  return (minute - peakStart + 1440) % 1440 < peakDuration
    ? PEAK_SECONDS : OFFPEAK_SECONDS;
}

function dailyRequests({peakSeconds, offpeakSeconds, peakHours, viewers}) {
  assert(Number.isInteger(peakHours) && peakHours >= 0 && peakHours <= 24);
  assert(peakSeconds > 0 && offpeakSeconds > 0 && viewers >= 0);
  return viewers * (peakHours * 3600 / peakSeconds +
    (24 - peakHours) * 3600 / offpeakSeconds);
}

test("owner settings: 10 viewers, six peak hours yield 27,000 GET/day", () => {
  assert.equal(dailyRequests({peakSeconds: 10, offpeakSeconds: 120, peakHours: 6, viewers: 10}), 27000);
  assert.equal(dailyRequests({peakSeconds: 5, offpeakSeconds: 5, peakHours: 6, viewers: 10}), 172800);
  assert.equal(1 - 27000 / 172800, 0.84375);
});

test("Taipei peak boundaries even when timestamp is UTC", () => {
  assert.equal(proposalInterval(new Date("2026-10-10T09:59:00Z")), 120); // 17:59 Taipei
  assert.equal(proposalInterval(new Date("2026-10-10T10:00:00Z")), 10);  // 18:00 Taipei
  assert.equal(proposalInterval(new Date("2026-10-10T15:59:00Z")), 10);  // 23:59 Taipei
  assert.equal(proposalInterval(new Date("2026-10-10T16:00:00Z")), 120); // 00:00 Taipei
});

test("background tabs do not schedule a new GET", () => {
  assert.equal(proposalInterval(new Date("2026-10-10T10:00:00Z"), {visible: false}), null);
  assert.equal(proposalInterval(new Date("2026-10-10T10:00:00Z"), {visible: true}), 10);
});

test("traffic model scales linearly and does not assume one viewer equals one write", () => {
  assert.equal(dailyRequests({peakSeconds: 10, offpeakSeconds: 120, peakHours: 6, viewers: 1}), 2700);
  assert.equal(dailyRequests({peakSeconds: 10, offpeakSeconds: 120, peakHours: 6, viewers: 100}), 270000);
});
