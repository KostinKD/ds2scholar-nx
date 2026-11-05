"""Offline, transactional import of a reviewed world payload into a stopped VPS.

The deployment wrapper must stop the service and restart it after this finishes.
Receipts live in the same transaction as their rows, allowing safe retries.
"""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

TABLES={'message':('BloodMessages','MessageId'),'blood':('Bloodstains','BloodstainId'),'ghost':('Ghosts','GhostId')}


def apply(database,config,payload_path,backup_dir,expected_sha):
    raw=payload_path.read_bytes();bundle=hashlib.sha256(raw).hexdigest()
    if bundle!=expected_sha:raise ValueError('Payload SHA mismatch')
    payload=json.loads(raw)
    if payload['counts']!=dict(message=2400,ghost=3540,blood=1115):raise ValueError('Unexpected batch counts')
    if dict(Counter(e['kind'] for e in payload['entries']))!=payload['counts']:raise ValueError('Invalid entry counts')
    backup_dir.mkdir(parents=True,exist_ok=False)
    shutil.copy2(config,backup_dir/'config.json')
    with closing(sqlite3.connect(database)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='SocialWorldSeedRevision'").fetchone():
            if db.execute("SELECT 1 FROM SocialWorldSeedRevision WHERE BaseBundleId=? AND Status='active'",(bundle,)).fetchone():
                raise ValueError('This bundle has an active replay revision; import its current receipt instead')
        with closing(sqlite3.connect(backup_dir/'database.sqlite')) as backup:db.backup(backup)
        author=db.execute('SELECT PlayerId,PlayerSteamId,CharacterId FROM BloodMessages WHERE MessageId=14').fetchone()
        assert author==(payload['owner'],payload['xuid'],payload['character'])
        before={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table,_ in TABLES.values()}
        # No existing rows or player statistics are updated by this importer.
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS SocialWorldSeedReceipt (BundleId TEXT NOT NULL, Ordinal INTEGER NOT NULL, Kind TEXT NOT NULL, RecordId INTEGER NOT NULL, PayloadSha256 TEXT NOT NULL, PRIMARY KEY(BundleId,Ordinal))')
        receipts=[];added=Counter()
        try:
            for ordinal,e in enumerate(payload['entries']):
                kind=e['kind'];table,id_column=TABLES[kind]
                assert e['area']!=10040000 and 0<=e['cell']<=0xffffffff
                data=bytes.fromhex(e['data']);replay=bytes.fromhex(e['replay']) if kind=='blood' else None
                digest=hashlib.sha256(data+(replay or b'')).hexdigest()
                previous=db.execute('SELECT RecordId,PayloadSha256 FROM SocialWorldSeedReceipt WHERE BundleId=? AND Ordinal=?',(bundle,ordinal)).fetchone()
                if previous:
                    ident,saved_digest=previous;assert digest==saved_digest
                else:
                    columns=['OnlineAreaId','CellId','PlayerId','PlayerSteamId']
                    values=[e['area'],e['cell'],payload['owner'],payload['xuid']]
                    if kind=='message':columns+=['CharacterId','RatingPoor','RatingGood'];values+=[payload['character'],0,0]
                    columns+=['Data'];values+=[data]
                    if kind=='blood':columns+=['GhostData'];values+=[replay]
                    sql='INSERT INTO '+table+' ('+','.join(columns)+",CreatedTime) VALUES ("+','.join('?' for _ in values)+",datetime('now'))"
                    ident=db.execute(sql,values).lastrowid
                    db.execute('INSERT INTO SocialWorldSeedReceipt VALUES(?,?,?,?,?)',(bundle,ordinal,kind,ident,digest))
                    added[kind]+=1
                selected='OnlineAreaId,CellId,PlayerId,Data'+(',GhostData' if kind=='blood' else '')
                row=db.execute('SELECT '+selected+' FROM '+table+' WHERE '+id_column+'=?',(ident,)).fetchone()
                assert row==(e['area'],e['cell'],payload['owner'],data)+((replay,) if kind=='blood' else ())
                receipts.append(dict(ordinal=ordinal,kind=kind,id=ident,area=e['area'],cell=e['cell'],sha256=digest))
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            db.commit()
        except BaseException:
            db.rollback();raise
        after={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table,_ in TABLES.values()}
        for kind,(table,_) in TABLES.items():assert after[table]==before[table]+added[kind]
    settings=json.loads(config.read_text())
    overrides=dict(BloodstainMaxDatabaseEntries=100000,BloodMessagePrimeCountPerArea=512,
                   BloodMessageMaxLivePoolEntriesPerArea=512,BloodstainPrimeCountPerArea=512,
                   BloodstainMaxLivePoolEntriesPerArea=512,GhostPrimeCountPerArea=5000,
                   GhostMaxLivePoolEntriesPerArea=5000)
    settings.update(overrides)
    config.write_text(json.dumps(settings,indent=4)+'\n')
    result=dict(bundle=bundle,before=before,after=after,added=dict(added),config=overrides,receipts=receipts)
    (backup_dir/'receipt.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='receipts'}),flush=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('database','config','payload','backup-dir'):ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--sha256',required=True)
    ap.add_argument('--apply',action='store_true')
    args=ap.parse_args()
    if not args.apply:ap.error('Offline import requires explicit --apply')
    apply(args.database,args.config,args.payload,args.backup_dir,args.sha256)


if __name__=='__main__':main()
