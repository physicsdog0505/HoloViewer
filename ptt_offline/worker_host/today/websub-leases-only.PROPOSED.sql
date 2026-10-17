-- Proposal only. Minimal forward-only WebSub lease table; NOT applied to production.
-- Intentionally separate from Today/PTT/profile migrations.
CREATE TABLE IF NOT EXISTS public_today_websub_leases (
 channel_id TEXT PRIMARY KEY NOT NULL,
 roster_version TEXT NOT NULL,
 topic TEXT NOT NULL,
 requested_mode TEXT NOT NULL CHECK(requested_mode IN ('subscribe','unsubscribe')),
 state TEXT NOT NULL CHECK(state IN ('pending','active','expired','rejected')),
 requested_at TEXT,
 verified_at TEXT,
 expires_at TEXT,
 lease_seconds INTEGER,
 last_error TEXT
);
CREATE INDEX IF NOT EXISTS public_today_websub_leases_due
 ON public_today_websub_leases(state,expires_at);
