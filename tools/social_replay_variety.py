"""Select real replay variants whose complete paths fit existing placements."""
import argparse
from collections import Counter,defaultdict
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3
import struct
from social_seed import replay_positions,translate_replay,packed_position
from social_world import _triangles


class Surface:
    def __init__(self,meshes):
        self.index=defaultdict(list)
        for _,_,vs,_ in _triangles(meshes,-1000,1000):
            a,b,c=vs
            den=(b[2]-c[2])*(a[0]-c[0])+(c[0]-b[0])*(a[2]-c[2])
            if abs(den)<1e-8:continue
            triangle=(a,b,c,den)
            for x in range(math.floor(min(v[0] for v in vs)/4),math.floor(max(v[0] for v in vs)/4)+1):
                for z in range(math.floor(min(v[2] for v in vs)/4),math.floor(max(v[2] for v in vs)/4)+1):
                    self.index[x,z].append(triangle)

    def heights(self,x,z):
        result=[]
        for a,b,c,den in self.index.get((math.floor(x/4),math.floor(z/4)),()):
            u=((b[2]-c[2])*(x-c[0])+(c[0]-b[0])*(z-c[2]))/den
            v=((c[2]-a[2])*(x-c[0])+(a[0]-c[0])*(z-c[2]))/den
            w=1-u-v
            if min(u,v,w)>=-1e-6:result.append(u*a[1]+v*b[1]+w*c[1])
        return result

    def fits(self,poses,kind):
        if kind=='blood' and self.heights(poses[-1][0],poses[-1][2]):return False
        previous=poses[0]
        for point in poses:
            distance=math.dist(point,previous) if kind=='ghost' else math.hypot(point[0]-previous[0],point[2]-previous[2])
            steps=max(1,math.ceil(distance/.5))
            for j in range(1,steps+1):
                p=[previous[i]+(point[i]-previous[i])*j/steps for i in range(3)]
                heights=self.heights(p[0],p[2])
                if kind=='ghost':
                    if not any(abs(h-p[1])<=.35 for h in heights):return False
                elif any(h>p[1]+.6 for h in heights):return False
            previous=point
        return True


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--database',type=Path,required=True)
    ap.add_argument('--root',type=Path,default=Path('out/social_world/world'))
    ap.add_argument('--payload',type=Path)
    ap.add_argument('--receipt',type=Path)
    ap.add_argument('--output',type=Path)
    args=ap.parse_args();root=args.root
    payload=json.loads((args.payload or root/'payload.json').read_text())
    receipt=json.loads((args.receipt or root/'live_receipt.json').read_text())
    audit=json.loads(Path('out/social_world/variety-audit.json').read_text())
    with closing(sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        donors={}
        for kind,table,column,key in [('ghost','Ghosts','Data','GhostId'),('blood','Bloodstains','GhostData','BloodstainId')]:
            selected=[r for r in audit[kind] if kind=='blood' or r['distance']>1]
            donors[kind]=[]
            for item in selected:
                row=db.execute('SELECT '+column+(',Data' if kind=='blood' else '')+' FROM '+table+' WHERE '+key+'=? AND PlayerId<>7',(item['id'],)).fetchone()
                if not row:continue
                raw=row[0]
                assert hashlib.sha256(raw).hexdigest()==item['sha256']
                donors[kind].append((item,raw,row[1] if kind=='blood' else None))
    changes=[];usage=Counter();summary=Counter();area_summary=[]
    previous_area=None;surface=None
    for ordinal,(entry,record) in enumerate(zip(payload['entries'],receipt['receipts'])):
        assert ordinal==record['ordinal'] and entry['kind']==record['kind']
        kind=entry['kind']
        if kind=='message':continue
        if entry['area']!=previous_area:
            if previous_area is not None:print('AREA_VARIETY',previous_area,dict(summary),flush=True)
            previous_area=entry['area'];summary=Counter()
            map_id='m'+str(entry['area'])[:2]+'_'+str(entry['area'])[2:4]+'_00_00'
            surface=Surface(json.loads((root/(map_id+'.json')).read_text())['meshes'])
        candidates=list(donors[kind]);random.Random(ordinal+0x710000).shuffle(candidates)
        candidates.sort(key=lambda r:usage[kind,r[0]['id']])
        old_body=bytes.fromhex(entry['data'] if kind=='ghost' else entry['replay'])
        old_canonical=translate_replay(old_body,kind,[0,0,0],1,0)
        for donor,raw,metadata in candidates:
            if translate_replay(raw,kind,[0,0,0],1,0)==old_canonical:continue
            try:new=translate_replay(raw,kind,entry['position'],payload['owner'],0x710000+ordinal)
            except ValueError:continue
            if not surface.fits(replay_positions(new,kind),kind):continue
            data=entry['data'];replay=entry.get('replay')
            if kind=='ghost':data=new.hex()
            else:
                header=bytearray(metadata);struct.pack_into('>I',header,4,payload['owner']);header[8:14]=packed_position(entry['position'])
                data=bytes(header).hex();replay=new.hex()
            # Selecting the same source is useful only if the original scene
            # already had variety; it is not counted as a distinct replacement.
            changes.append(dict(ordinal=ordinal,id=record['id'],kind=kind,area=entry['area'],cell=entry['cell'],
                                old_data=entry['data'],old_replay=entry.get('replay'),data=data,replay=replay,
                                donor=donor['id'],source_sha256=donor['sha256']))
            usage[kind,donor['id']]+=1;summary[kind]+=1
            break
    if previous_area is not None:print('AREA_VARIETY',previous_area,dict(summary),flush=True)
    result=dict(base_bundle=receipt['bundle'],changes=changes,
                counts=dict(Counter(c['kind'] for c in changes)),
                sources={kind:len({c['donor'] for c in changes if c['kind']==kind}) for kind in donors})
    encoded=json.dumps(result,sort_keys=True,separators=(',',':')).encode()
    (args.output or root/'variety.json').write_bytes(encoded)
    print('VARIETY_READY',result['counts'],'sources',result['sources'],'sha256='+hashlib.sha256(encoded).hexdigest(),flush=True)


if __name__=='__main__':main()
