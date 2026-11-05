"""Replace only unchanged synthetic replay rows, retaining IDs and placements.

Run offline. The same revision supports guarded rollback and idempotent retry.
"""
import argparse
from contextlib import closing
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
from social_world_import import TABLES


def digest(data,replay=None):
    return hashlib.sha256(bytes.fromhex(data)+(bytes.fromhex(replay) if replay else b'')).hexdigest()


def revise(database,revision_path,backup_dir,expected_sha,rollback=False):
    raw=revision_path.read_bytes()
    if raw[:2]==b'\x1f\x8b':raw=gzip.decompress(raw)
    bundle=hashlib.sha256(raw).hexdigest()
    if bundle!=expected_sha:raise ValueError('Revision SHA mismatch')
    revision=json.loads(raw);base=revision['base_bundle'];changes=revision['changes']
    receipt_count=revision.get('receipt_count',7055)
    bootstrap=revision.get('bootstrap_receipts',[])
    if bootstrap:
        assert receipt_count==8 and len(bootstrap)==8
        assert {r['kind'] for r in bootstrap}=={'blood','ghost'}
        assert all(r['area']==10040000 for r in bootstrap)
    if len({c['ordinal'] for c in changes})!=len(changes):raise ValueError('Duplicate ordinal')
    if len({(c['kind'],c['id']) for c in changes})!=len(changes):raise ValueError('Duplicate row')
    if any(c['kind'] not in ('blood','ghost') for c in changes):raise ValueError('Only replay records may change')
    backup_dir.mkdir(parents=True,exist_ok=False)
    with closing(sqlite3.connect(database)) as db:
        with closing(sqlite3.connect(backup_dir/'database.sqlite')) as backup:db.backup(backup)
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        source,target=(bundle,base) if rollback else (base,bundle)
        db.execute('BEGIN IMMEDIATE')
        try:
            active=db.execute('SELECT count(*) FROM SocialWorldSeedReceipt WHERE BundleId=?',(source,)).fetchone()[0]
            already=db.execute('SELECT count(*) FROM SocialWorldSeedReceipt WHERE BundleId=?',(target,)).fetchone()[0]
            if bootstrap and not rollback and active==already==0:
                for r in bootstrap:
                    table,key=TABLES[r['kind']]
                    selected='PlayerId,PlayerSteamId,OnlineAreaId,CellId,Data'+(',GhostData' if r['kind']=='blood' else '')
                    row=db.execute('SELECT '+selected+' FROM '+table+' WHERE '+key+'=?',(r['id'],)).fetchone()
                    expected=(7,'0xD520000000000001',r['area'],r['cell'],bytes.fromhex(r['data']))
                    if r['kind']=='blood':expected+=(bytes.fromhex(r['replay']),)
                    assert row==expected,('Pilot record changed',r['kind'],r['id'])
                    assert not db.execute('SELECT 1 FROM SocialWorldSeedReceipt WHERE Kind=? AND RecordId=?',(r['kind'],r['id'])).fetchone()
                    db.execute('INSERT INTO SocialWorldSeedReceipt VALUES(?,?,?,?,?)',(base,r['ordinal'],r['kind'],r['id'],digest(r['data'],r.get('replay'))))
                active=receipt_count
            assert (active,already) in ((receipt_count,0),(0,receipt_count)),(active,already)
            # Validate every current row before making any update.
            for c in changes:
                kind=c['kind'];table,key=TABLES[kind]
                current_new=(rollback and active) or (not rollback and already)
                data,replay=(c['data'],c['replay']) if current_new else (c['old_data'],c['old_replay'])
                selected='PlayerId,PlayerSteamId,OnlineAreaId,CellId,Data'+(',GhostData' if kind=='blood' else '')
                row=db.execute('SELECT '+selected+' FROM '+table+' WHERE '+key+'=?',(c['id'],)).fetchone()
                expected=(7,'0xD520000000000001',c['area'],c['cell'],bytes.fromhex(data))
                if kind=='blood':expected+=(bytes.fromhex(replay),)
                assert row==expected,('Record changed',kind,c['id'])
                receipt=db.execute('SELECT Kind,RecordId,PayloadSha256 FROM SocialWorldSeedReceipt WHERE BundleId=? AND Ordinal=?',(source if active else target,c['ordinal'])).fetchone()
                assert receipt==(kind,c['id'],digest(data,replay))
            if active:
                for c in changes:
                    kind=c['kind'];table,key=TABLES[kind]
                    data,replay=(c['old_data'],c['old_replay']) if rollback else (c['data'],c['replay'])
                    values=[bytes.fromhex(data)]
                    sql='UPDATE '+table+' SET Data=?'
                    if kind=='blood':sql+=',GhostData=?';values.append(bytes.fromhex(replay))
                    db.execute(sql+' WHERE '+key+'=?',values+[c['id']])
                    db.execute('UPDATE SocialWorldSeedReceipt SET PayloadSha256=? WHERE BundleId=? AND Ordinal=?',(digest(data,replay),source,c['ordinal']))
                db.execute('UPDATE SocialWorldSeedReceipt SET BundleId=? WHERE BundleId=?',(target,source))
                db.execute('CREATE TABLE IF NOT EXISTS SocialWorldSeedRevision (BaseBundleId TEXT PRIMARY KEY,RevisionBundleId TEXT NOT NULL,Status TEXT NOT NULL)')
                db.execute('INSERT OR REPLACE INTO SocialWorldSeedRevision VALUES(?,?,?)',(base,bundle,'rolled-back' if rollback else 'active'))
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            db.commit()
        except BaseException:
            db.rollback();raise
        receipts=[dict(ordinal=o,kind=k,id=i,sha256=h) for o,k,i,h in db.execute('SELECT Ordinal,Kind,RecordId,PayloadSha256 FROM SocialWorldSeedReceipt WHERE BundleId=? ORDER BY Ordinal',(target,))]
        result=dict(bundle=target,base_bundle=base,changed=len(changes) if active else 0,counts=revision['counts'],sources=revision['sources'],receipts=receipts)
        (backup_dir/'receipt.json').write_text(json.dumps(result,indent=2))
        print(json.dumps({k:v for k,v in result.items() if k!='receipts'}),flush=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('database','revision','backup-dir'):ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--sha256',required=True)
    ap.add_argument('--rollback',action='store_true')
    ap.add_argument('--apply',action='store_true')
    args=ap.parse_args()
    if not args.apply:ap.error('Offline revision requires --apply')
    revise(args.database,args.revision,args.backup_dir,args.sha256,args.rollback)


if __name__=='__main__':main()
