"""Remove only unchanged records belonging to one import receipt, offline."""
import argparse
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
from social_world_import import TABLES


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--database',type=Path,required=True)
    ap.add_argument('--bundle',required=True)
    ap.add_argument('--apply',action='store_true')
    args=ap.parse_args()
    with closing(sqlite3.connect(args.database)) as db:
        db.execute('BEGIN IMMEDIATE')
        rows=db.execute('SELECT Kind,RecordId,PayloadSha256 FROM SocialWorldSeedReceipt WHERE BundleId=?',(args.bundle,)).fetchall()
        if not rows:raise ValueError('Bundle not found')
        for kind,ident,digest in rows:
            table,column=TABLES[kind]
            row=db.execute('SELECT PlayerId,PlayerSteamId,Data'+(',GhostData' if kind=='blood' else '')+' FROM '+table+' WHERE '+column+'=?',(ident,)).fetchone()
            if not row or row[:2]!=(7,'0xD520000000000001'):raise ValueError('Synthetic author mismatch')
            if hashlib.sha256(b''.join(row[2:])).hexdigest()!=digest:raise ValueError('Record changed after import')
        if args.apply:
            for kind,ident,_ in rows:
                table,column=TABLES[kind]
                db.execute('DELETE FROM '+table+' WHERE '+column+'=?',(ident,))
            db.execute('DELETE FROM SocialWorldSeedReceipt WHERE BundleId=?',(args.bundle,))
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            db.commit()
        else:db.rollback()
        print('REMOVED' if args.apply else 'ROLLBACK_READY',len(rows))


if __name__=='__main__':main()
