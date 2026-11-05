"""Build the approved world batch using the proven Xbox social codecs."""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
from social_seed import message_payload, packed_position, translate_replay, replay_positions


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--database',type=Path,required=True)
    ap.add_argument('--batch',type=Path,default=Path('out/social_world/world/batch.json'))
    ap.add_argument('--output',type=Path,default=Path('out/social_world/world/payload.json'))
    args=ap.parse_args()
    with closing(sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        owner,xuid,character,note=db.execute('SELECT PlayerId,PlayerSteamId,CharacterId,Data FROM BloodMessages WHERE MessageId=14').fetchone()
        assert xuid=='0xD520000000000001' and owner==7
        metadata,death=db.execute('SELECT Data,GhostData FROM Bloodstains WHERE OnlineAreaId=10040000 ORDER BY BloodstainId LIMIT 1').fetchone()
        ghost=db.execute('SELECT Data FROM Ghosts WHERE OnlineAreaId=10040000 ORDER BY GhostId LIMIT 1').fetchone()[0]
    entries=[]
    choices=[(0,9110),(0,1370),(0,5290),(6,10260),(0,9040)]
    for area in json.loads(args.batch.read_text()):
        assert area['area']!=10040000
        for p in area['placements']:
            index=len(entries);kind=p['kind'];position=p['position']
            entry=dict(area=area['area'],cell=p['cell'],kind=kind,position=position)
            if kind=='message':
                sentence,word=choices[index%len(choices)]
                entry['data']=message_payload(note,position,sentence,word).hex()
            elif kind=='ghost':
                entry['data']=translate_replay(ghost,kind,position,owner,0x610000+index).hex()
            elif kind=='blood':
                data=bytearray(metadata);struct.pack_into('>I',data,4,owner);data[8:14]=packed_position(position)
                entry['data']=bytes(data).hex()
                entry['replay']=translate_replay(death,kind,position,owner,0x610000+index).hex()
                replay_positions(bytes.fromhex(entry['replay']),kind)
            else:raise ValueError(kind)
            entries.append(entry)
    counts=dict(Counter(e['kind'] for e in entries))
    assert counts==dict(message=2400,ghost=3540,blood=1115),counts
    payload=dict(owner=owner,xuid=xuid,character=character,counts=counts,entries=entries)
    encoded=json.dumps(payload,sort_keys=True,separators=(',',':')).encode()
    args.output.write_bytes(encoded)
    print('PAYLOAD_READY',counts,'bytes='+str(len(encoded)),'sha256='+hashlib.sha256(encoded).hexdigest())


if __name__=='__main__':main()
