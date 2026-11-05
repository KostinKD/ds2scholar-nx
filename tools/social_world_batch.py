"""Prepare navigation-based placements for all available SotFS base maps.

Outputs candidates, never uploads them. Coordinates are map local, as confirmed
by existing records and cell IDs in six distinct online areas.
"""
import collections
import argparse
import json
import math
from pathlib import Path
import random
import sqlite3
from contextlib import closing
from social_seed import cell_id, network_grid, replay_positions
from social_world import _triangles


def prepare(meshes, death, seed, multipliers=None):
    rng = random.Random(seed)
    triangles = list(_triangles(meshes, -1000, 1000))
    grid = collections.defaultdict(list)
    for index, (_, _, vs, _) in enumerate(triangles):
        for x in range(math.floor(min(v[0] for v in vs)/10), math.floor(max(v[0] for v in vs)/10)+1):
            for z in range(math.floor(min(v[2] for v in vs)/10), math.floor(max(v[2] for v in vs)/10)+1):
                grid[x, z].append(index)

    def heights(x, z):
        result = []
        for index in grid.get((math.floor(x/10), math.floor(z/10)), []):
            a,b,c = triangles[index][2]
            den = (b[2]-c[2])*(a[0]-c[0])+(c[0]-b[0])*(a[2]-c[2])
            if abs(den)<1e-8: continue
            u=((b[2]-c[2])*(x-c[0])+(c[0]-b[0])*(z-c[2]))/den
            v=((c[2]-a[2])*(x-c[0])+(a[0]-c[0])*(z-c[2]))/den
            w=1-u-v
            if min(u,v,w)>=0: result.append(u*a[1]+v*b[1]+w*c[1])
        return result

    poses = replay_positions(death, 'blood')
    delta = [[p[i]-poses[0][i] for i in range(3)] for p in poses]
    pool=[]
    for mesh,face,vs,area in triangles:
        for _ in range(max(1,min(12,math.ceil(area/50)))):
            r=math.sqrt(rng.random()); s=rng.random(); weights=(1-r,r*(1-s),r*s)
            p=[sum(weights[j]*vs[j][i] for j in range(3)) for i in range(3)]
            p[1]+=.05
            if all(abs(v)<1000 for v in p): pool.append(dict(position=p,surface=[mesh,face]))
    rng.shuffle(pool)
    chosen=[]; spatial=collections.defaultdict(list)
    for point in pool:
        p=point['position']; key=tuple(math.floor(v/14) for v in p)
        near=[q for dx in (-1,0,1) for dy in (-1,0,1) for dz in (-1,0,1)
              for q in spatial.get((key[0]+dx,key[1]+dy,key[2]+dz),[])]
        if any(sum((p[i]-q[i])**2 for i in range(3))<196 for q in near):continue
        point['kind']='ghost' if len(chosen)%3==2 else 'message'
        chosen.append(point);spatial[key].append(p)
    blood=[]
    for point in pool:
        p=point['position']
        if any(sum((p[i]-q['position'][i])**2 for i in range(3))<400 for q in blood):continue
        if heights(p[0]+delta[-1][0],p[2]+delta[-1][2]):continue
        if any(any(h>p[1]+dy+.6 for h in heights(p[0]+dx,p[2]+dz)) for dx,dy,dz in delta[::3]):continue
        blood.append(point|dict(kind='blood'))
        if len(blood)>=max(4,len(chosen)//8):break
    baseline = chosen+blood
    if multipliers is None:
        return baseline
    targets = {kind: sum(p['kind']==kind for p in baseline)*factor
               for kind, factor in multipliers.items()}
    # A denser candidate pool provides distinct positions, rather than copying
    # existing marks at the same coordinates. Keep the original fall checks.
    dense=[]
    for mesh,face,vs,area in triangles:
        for _ in range(6):
            r=math.sqrt(rng.random());s=rng.random();weights=(1-r,r*(1-s),r*s)
            p=[sum(weights[j]*vs[j][i] for j in range(3)) for i in range(3)]
            p[1]+=.05
            if all(abs(v)<1000 for v in p):dense.append(dict(position=p,surface=[mesh,face]))
    rng.shuffle(dense)
    result=[]
    used=set()
    for kind in ('blood','ghost','message'):
        candidates=dense
        if kind=='blood':
            candidates=[]
            for point in dense:
                p=point['position']
                if heights(p[0]+delta[-1][0],p[2]+delta[-1][2]):continue
                if any(any(h>p[1]+dy+.6 for h in heights(p[0]+dx,p[2]+dz)) for dx,dy,dz in delta[::3]):continue
                candidates.append(point)
                if len(candidates)>=targets[kind]*12:break
        selected=[]
        # Gradually reduce spacing only when the requested count needs it.
        for spacing in (8,6,4,2,1):
            index=collections.defaultdict(list)
            for p in selected:
                index[tuple(math.floor(v/spacing) for v in p['position'])].append(p['position'])
            for point in candidates:
                if len(selected)>=targets[kind]:break
                p=point['position']
                if tuple(p) in used:continue
                key=tuple(math.floor(v/spacing) for v in p)
                near=(q for dx in (-1,0,1) for dy in (-1,0,1) for dz in (-1,0,1)
                      for q in index.get((key[0]+dx,key[1]+dy,key[2]+dz),[]))
                if any(sum((p[i]-q[i])**2 for i in range(3))<spacing**2 for q in near):continue
                selected.append(point|dict(kind=kind));index[key].append(p);used.add(tuple(p))
            if len(selected)>=targets[kind]:break
        if len(selected)!=targets[kind]:
            raise ValueError(f'Area {seed}: only {len(selected)} compatible {kind} positions for target {targets[kind]}')
        result.extend(selected)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--messages',type=int,default=2)
    parser.add_argument('--ghosts',type=int,default=6)
    parser.add_argument('--blood',type=int,default=5)
    args=parser.parse_args()
    if min(args.messages,args.ghosts,args.blood)<1:parser.error('Multipliers must be positive')
    multipliers=dict(message=args.messages,ghost=args.ghosts,blood=args.blood)
    root=Path('out/social_world/world')
    inventory=json.loads((root/'inventory.json').read_text())
    param=Path('out/social_world/NetworkAreaParam.param').read_bytes()
    with closing(sqlite3.connect('file:G:/DS2Switch/vps_data/default/database.sqlite?mode=ro',uri=True)) as db:
        death=db.execute('SELECT GhostData FROM Bloodstains WHERE OnlineAreaId=10040000 ORDER BY BloodstainId LIMIT 1').fetchone()[0]
    result=[]
    for record in inventory:
        if record['area']==10040000:continue
        data=json.loads((root/(record['map']+'.json')).read_text())
        points=prepare(data['meshes'],death,record['area'],multipliers)
        grid=network_grid(param,record['area'])
        for p in points:p['cell']=cell_id(p['position'],grid)
        item=dict(map=record['map'],area=record['area'],multipliers=multipliers,placements=points)
        result.append(item)
        print(record['map'],dict(collections.Counter(p['kind'] for p in points)),flush=True)
    (root/'batch.json').write_text(json.dumps(result,indent=2))
    print('TOTAL',sum(len(r['placements']) for r in result),flush=True)


if __name__=='__main__':main()
