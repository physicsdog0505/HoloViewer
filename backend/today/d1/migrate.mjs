/**
 * #47 forward-only D1 schema provenance. Call ONLY during separately approved
 * migration; importing this file has no Cloudflare side effects.
 *
 * D1 batch statements are transactional. The exact SQL body is supplied by the
 * deployment owner; checksum is SHA-256 of exact UTF-8 bytes.
 */
export const TODAY_MIGRATION_ID='0002_today_canonical';
const LEDGER_SQL=`CREATE TABLE IF NOT EXISTS public_today_schema_migrations (
  migration_id TEXT PRIMARY KEY NOT NULL,
  checksum TEXT NOT NULL,
  applied_at TEXT NOT NULL
)`;
export async function sha256Hex(sql) {
  if (typeof sql!=='string' || !sql.trim()) throw Error('empty migration');
  const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(sql));
  return [...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,'0')).join('');
}
export function splitMigrationSql(sql) {
  // Our locked migration has plain CREATE TABLE / INDEX; no triggers or quoted semicolons.
  // Fail closed rather than executing unsupported SQL shape.
  if (typeof sql!=='string') throw Error('unsafe migration SQL');
  const withoutComments=sql.split('\n').map(line=>line.trimStart().startsWith('--')?'':line).join('\n');
  if (/\b(DROP|TRUNCATE|DELETE|REPLACE|ATTACH|VACUUM)\b/i.test(withoutComments))
    throw Error('unsafe migration SQL');
  const statements=withoutComments.split(';').map(v=>v.trim()).filter(Boolean);
  if (!statements.length || statements.some(v=>!/^CREATE (TABLE|INDEX) IF NOT EXISTS\b/i.test(v)))
    throw Error('unsupported migration SQL');
  return statements;
}
export async function applyTodayMigration(db,{sql,migrationId=TODAY_MIGRATION_ID,appliedAt}={}) {
  if (!db?.prepare || !db?.batch || migrationId!==TODAY_MIGRATION_ID)
    throw Error('unsupported migration target');
  const statements=splitMigrationSql(sql),checksum=await sha256Hex(sql);
  const timestamp=appliedAt??new Date().toISOString().replace(/\.\d{3}Z$/,'Z');
  if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(timestamp))
    throw Error('invalid applied_at');
  // Bootstrap table is idempotent. If a batch fails, no ledger record is made.
  await db.prepare(LEDGER_SQL).run();
  const existing=await db.prepare('SELECT checksum FROM public_today_schema_migrations WHERE migration_id=?')
    .bind(migrationId).first();
  if (existing) {
    if (existing.checksum!==checksum) throw Error('migration checksum drift');
    return {applied:false,migrationId,checksum};
  }
  const actions=statements.map(statement=>db.prepare(statement));
  actions.push(db.prepare(`INSERT INTO public_today_schema_migrations(migration_id,checksum,applied_at)
    VALUES (?,?,?)`).bind(migrationId,checksum,timestamp));
  await db.batch(actions);
  // Re-read is mandatory: a racing applier with another checksum must fail.
  const recorded=await db.prepare('SELECT checksum FROM public_today_schema_migrations WHERE migration_id=?')
    .bind(migrationId).first();
  if (recorded?.checksum!==checksum) throw Error('migration provenance mismatch');
  return {applied:true,migrationId,checksum};
}
