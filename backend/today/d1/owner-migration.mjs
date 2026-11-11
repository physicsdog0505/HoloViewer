/** #47 one-shot Today D1 migration entrypoint for the EXISTING API Worker only.
 * Not mounted as a public HTTP path. Owner must integrate into verified Worker
 * startup/admin execution transport and approve it separately.
 */
import {applyTodayMigration,sha256Hex,TODAY_MIGRATION_ID} from './migrate.mjs';
const EXPECTED_ACCOUNT='f5999f88acc7aa8855f0896eef5d9942';
const EXPECTED_D1='64e1a0ee-1455-4377-9640-3922e8f4d061';
const EXPECTED_BLOB='943e3d49f665060a2f0b71c7ffef44185d754244';
export const TARGET=Object.freeze({accountId:EXPECTED_ACCOUNT,databaseId:EXPECTED_D1,migrationId:TODAY_MIGRATION_ID,gitBlob:EXPECTED_BLOB});
export async function executeOwnerTodayMigration({db,sql,accountId,databaseId,expectedSha256,authorized=false,appliedAt}={}){
 if(!authorized)throw Error('explicit owner execution approval required');
 if(accountId!==EXPECTED_ACCOUNT||databaseId!==EXPECTED_D1)throw Error('production identity mismatch');
 if(!db?.prepare||!db?.batch)throw Error('D1 binding unavailable');
 if(typeof expectedSha256!=='string'||!/^[0-9a-f]{64}$/.test(expectedSha256))throw Error('pinned sha256 required');
 const actual=await sha256Hex(sql);
 if(actual!==expectedSha256)throw Error('migration SHA-256 mismatch');
 return applyTodayMigration(db,{sql,appliedAt,migrationId:TODAY_MIGRATION_ID});
}
