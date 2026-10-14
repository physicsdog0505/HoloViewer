# 4174 → Public UI migration — checkpoint 2026-10-15

## Frozen target
Private `physicsdog0505/Hololive-PTT-Viewer` accepted UI source `cab0adb51b627205e39541d7b985258fb861fb24`; no independent Public UI redesign.

## Integrated Public baseline
Main prior to this checkpoint: `c076098436aba6b7b9759c2fd7377ab7aa2b703e`, after #50 fixed primary focus / target consistency and #49 removed Public-only 12-video cap.

## This checkpoint: linked video control
- Connected previously inert **連動播放／暫停** checkbox to *mounted* YouTube IFrame API state events.
- Command forwarding is restricted to currently mounted iframe `contentWindow`, known YouTube embed origins, and only play/pause state events.
- Per-target 1-second echo suppression avoids feedback loops.
- Multi-view sessions default to linked playback ON, matching original 4174; one-view sessions OFF.
- Never auto-start streams and never fabricate timeline synchronization; no polling, new APIs or full iframe remount.

## Acceptance / limits
- Python smoke and JS syntax CI required before merge.
- Real browser operator still needs to confirm play/pause behavior; iframe browser-policy and YouTube limitations can prevent controls.
- UI parity remains **in progress**, not 100% accepted.
- Cloudflare deployment remains manual; avoid deploying intermediate versions without operator acknowledgement.
- API/data handoffs separate: #45 Public consumer contracts, #48 PTT.
- No D1, Worker, PTT Collector, production access or 4174 local modification.
