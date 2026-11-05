"""Read SotFS 360 navigation geometry and prepare non-deployable social drafts.

Format evidence: SoulsFormats NGP.cs and MSB2/PartsParam.cs (MIT).
Supports the big-endian NVG2 v1 / 32-bit MSB format present in this game's data.
Never writes game archives, server databases, or the owner's source annotation.
"""
import argparse
from bisect import bisect_left
import hashlib
import json
import math
from pathlib import Path
import random
import struct

from extract_navmesh import Bxf4Archive, decompress_dcx


def decode_position(data: bytes, kind: str) -> list[float]:
    """Read only: signed int16 XYZ / 32; does not claim playback can be moved.

    SotFS: message sub_82440930, stain sub_824452F0 call sub_82698CD8
    with shift=5. Ghost header correspondence is observed, not playback proof.
    """
    if kind == 'message' and len(data) == 24 and data[:4] in (b'\0\0\0\1', b'\0\0\0\2'):
        offset = 4
    elif kind == 'blood' and len(data) == 16 and data[:4] == b'\0\x39\0\x0b':
        offset = 8
    elif kind == 'ghost' and len(data) >= 14 and data[:4] == b'\0\x39\0\x0a':
        offset = 4
    else:
        raise ValueError('Unsupported Xbox social record header or length')
    return [v/32 for v in _unpack(data, '>3h', offset)]


def _unpack(data, fmt, offset):
    size = struct.calcsize(fmt)
    if offset < 0 or offset + size > len(data):
        raise ValueError(f'Truncated or invalid offset: {offset:#x}, size={size}')
    return struct.unpack_from(fmt, data, offset)


def _utf16(data, offset):
    for end in range(offset, len(data) - 1, 2):
        if data[end:end+2] == b'\0\0':
            try:
                return data[offset:end].decode('utf-16-be')
            except UnicodeError as exc:
                raise ValueError('Invalid MSB string') from exc
        if end - offset > 2048:
            break
    raise ValueError('Unterminated MSB string')


def read_ngp(data: bytes) -> list[dict]:
    if data[:8] != b'NVG2\0\1\0\0':
        raise ValueError('Expected big-endian NVG2 v1 (Xbox 360)')
    count, = _unpack(data, '>I', 8)
    if not 0 < count <= 4096:
        raise ValueError('Invalid mesh count')
    offsets = _unpack(data, f'>{count}I', 48)
    meshes = []
    for mesh_id, offset in enumerate(offsets):
        vc, fc = _unpack(data, '>Ih', offset + 36)
        if not 0 < vc <= 32768 or not 0 <= fc <= 32767:
            raise ValueError('Invalid vertex/face count')
        vo, _, fo = _unpack(data, '>III', offset + 52)
        vertices = [list(_unpack(data, '>3f', vo + i * 12)) for i in range(vc)]
        if not all(math.isfinite(v) for p in vertices for v in p):
            raise ValueError('Non-finite navigation vertex')
        faces = [list(_unpack(data, '>3h', fo + i * 12)) for i in range(fc)]
        if any(i < 0 or i >= vc for f in faces for i in f):
            raise ValueError('Invalid navigation face index')
        # Last six bytes of each face are connectivity/flags, not more vertices.
        if fc:
            _unpack(data, '>6h', fo + (fc - 1) * 12)
        meshes.append(dict(id=mesh_id, offset=offset, vertices=vertices, faces=faces))
    return meshes


def read_msb_objects(data: bytes) -> list[dict]:
    offset, seen = 0, set()
    objects = []
    while offset not in seen:
        seen.add(offset)
        version, name_offset, count = _unpack(data, '>III', offset)
        if version not in (0, 5) or not 0 < count <= 100000:
            raise ValueError('Invalid MSB section')
        name = _utf16(data, name_offset)
        offsets = _unpack(data, f'>{count}I', offset + 12)
        if name == 'PARTS_PARAM_ST':
            for p in offsets[:-1]:
                name_delta, = _unpack(data, '>I', p)
                kind, = _unpack(data, '>B', p + 4)
                pos = list(_unpack(data, '>3f', p + 12))
                if not all(math.isfinite(v) for v in pos):
                    raise ValueError('Non-finite MSB position')
                if kind == 1:
                    objects.append(dict(name=_utf16(data, p + name_delta),
                                        position=pos, msb_offset=p))
        offset = offsets[-1]
        if offset == 0:
            return objects
    raise ValueError('Cyclic MSB section chain')


def _triangles(meshes, min_y, max_y):
    for mesh in meshes:
        for face_id, face in enumerate(mesh['faces']):
            a, b, c = [mesh['vertices'][i] for i in face]
            if not all(min_y <= p[1] <= max_y for p in (a, b, c)):
                continue
            u, v = [b[i]-a[i] for i in range(3)], [c[i]-a[i] for i in range(3)]
            normal = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
            length = math.sqrt(sum(n*n for n in normal))
            if length < 1e-7 or abs(normal[1])/length < math.cos(math.radians(40)):
                continue
            yield mesh['id'], face_id, (a, b, c), abs(normal[1])/2


def _validate_zone(zone: dict):
    for k in ('x', 'z', 'radius', 'min_y', 'max_y'):
        if not isinstance(zone.get(k), (float, int)) or not math.isfinite(zone[k]):
            raise ValueError(f'Invalid zone {k}')
    kinds = zone.get('kinds')
    if (zone['radius'] <= 0 or zone['min_y'] >= zone['max_y']
            or not isinstance(zone.get('count'), int) or not 1 <= zone['count'] <= 2000
            or not isinstance(zone.get('seed'), int)
            or not isinstance(kinds, list) or not kinds or len(kinds) != len(set(kinds))
            or any(k not in ('message', 'blood', 'ghost') for k in kinds)):
        raise ValueError('Invalid zone limits or kinds')


def plan_zone(meshes: list[dict], zone: dict) -> dict:
    """Area-weighted sampling on triangles, retaining surface identity and height."""
    _validate_zone(zone)
    kinds = zone['kinds']
    triangles = list(_triangles(meshes, zone['min_y'], zone['max_y']))
    cumulative, total = [], 0
    for _, _, _, area in triangles:
        total += area
        cumulative.append(total)
    rng, placements = random.Random(zone['seed']), []
    # Round robin then shuffle guarantees representation when count >= len(kinds).
    labels = [kinds[i % len(kinds)] for i in range(zone['count'])]
    rng.shuffle(labels)
    for _ in range(zone['count'] * 2000 if total else 0):
        idx = min(bisect_left(cumulative, rng.random()*total), len(triangles)-1)
        mesh_id, face_id, vs, _ = triangles[idx]
        r, t = math.sqrt(rng.random()), rng.random()
        weights = (1-r, r*(1-t), r*t)
        pos = [sum(weights[j]*vs[j][i] for j in range(3)) for i in range(3)]
        if math.hypot(pos[0]-zone['x'], pos[2]-zone['z']) > zone['radius']:
            continue
        if any(math.hypot(pos[0]-p['position'][0], pos[2]-p['position'][2]) < 1.0
               for p in placements):
            continue
        placements.append(dict(kind=labels[len(placements)], position=pos,
                               surface=dict(mesh=mesh_id, face=face_id),
                               status='navigation-candidate-not-game-verified'))
        if len(placements) == zone['count']:
            break
    return dict(version=1, map='m10_04_00_00', coordinate_space='world',
                deployable=False, zone=zone, placements=placements,
                unplaced=zone['count']-len(placements),
                limitations=['Map alignment and player access require game verification.',
                             'Navmesh is not a guarantee of clearance or absence of dynamic objects.',
                             'Ghost/death recordings and message payloads are not generated.'])


def require_deployable(bundle: dict):
    if bundle.get('deployable') is not True or any(
            p.get('status') != 'game-verified' for p in bundle.get('placements', [])):
        raise ValueError('Draft coordinates cannot be deployed before calibration and gameplay validation')


def validate_world_draft(meshes: list[dict], draft: dict, geometry_sha256: str) -> dict:
    """Reopen a saved annotation only on its exact source geometry."""
    if (draft.get('version') != 1 or draft.get('map') != 'm10_04_00_00'
            or draft.get('coordinate_space') != 'world'
            or draft.get('source_ngp_sha256') != geometry_sha256):
        raise ValueError('Draft map/geometry does not match the current game')
    _validate_zone(draft['zone'])
    rows = draft.get('placements')
    if not isinstance(rows, list) or len(rows) > 2000:
        raise ValueError('Invalid saved placement count')
    lookup = {m['id']: m for m in meshes}
    checked = []
    for row in rows:
        p, surface = row.get('position'), row.get('surface', {})
        if (row.get('kind') not in ('message', 'blood', 'ghost')
                or not isinstance(p, list) or len(p) != 3
                or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in p)):
            raise ValueError('Invalid saved placement')
        mesh = lookup.get(surface.get('mesh'))
        face_id = surface.get('face')
        if mesh is None or not isinstance(face_id, int) or not 0 <= face_id < len(mesh['faces']):
            raise ValueError('Unknown saved navigation surface')
        a, b, c = [mesh['vertices'][i] for i in mesh['faces'][face_id]]
        den = (b[2]-c[2])*(a[0]-c[0]) + (c[0]-b[0])*(a[2]-c[2])
        if abs(den) < 1e-8:
            raise ValueError('Degenerate saved navigation surface')
        u = ((b[2]-c[2])*(p[0]-c[0]) + (c[0]-b[0])*(p[2]-c[2])) / den
        v = ((c[2]-a[2])*(p[0]-c[0]) + (a[0]-c[0])*(p[2]-c[2])) / den
        w = 1-u-v
        if min(u, v, w) < -1e-6 or abs(u*a[1]+v*b[1]+w*c[1]-p[1]) > 0.05:
            raise ValueError('Saved point is outside its navigation surface')
        checked.append(dict(kind=row['kind'], position=p, surface=surface,
                            status='navigation-candidate-not-game-verified'))
    return draft | {'placements': checked, 'deployable': False}


def create_preview(meshes, objects, bundle, target):
    template = Path(__file__).with_name('social_editor').joinpath('ground-preview.html').read_text(encoding='utf-8')
    data = dict(meshes=meshes, objects=objects, bundle=bundle)
    # This generated, local HTML includes extracted geometry: it stays under ignored out/.
    target.write_text(template.replace('/*__DATA__*/null', json.dumps(data).replace('<', '\\u003c')),
                      encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--game-root', type=Path, default=Path('assets/game_root'))
    ap.add_argument('--output', type=Path, default=Path('out/social_world/majula'))
    ap.add_argument('--center', nargs=2, type=float, default=[-20, -15], metavar=('X', 'Z'))
    ap.add_argument('--radius', type=float, default=65)
    ap.add_argument('--height', nargs=2, type=float, default=[0, 18], metavar=('MIN', 'MAX'))
    args = ap.parse_args()
    project = json.loads(args.project.read_text(encoding='utf-8-sig'))
    archive = Bxf4Archive(str(args.game_root/'GameData1.bhd'), str(args.game_root/'GameData1.bdt'))
    try:
        ngp = decompress_dcx(archive.read_file('map/m10_04_00_00/m10_04_00_00.ngp'))
        msb = decompress_dcx(archive.read_file('map/m10_04_00_00/m10_04_00_00.msb'))
    finally:
        archive.close()
    meshes, objects = read_ngp(ngp), read_msb_objects(msb)
    ngp_sha = hashlib.sha256(ngp).hexdigest()
    if project.get('coordinate_space') == 'world':
        bundle = validate_world_draft(meshes, project, ngp_sha)
    else:
        if project.get('map') != 'majula-schematic' or project.get('coordinate_space') != 'editor-only':
            ap.error('Expected original Majula schematic annotation or saved world draft')
        zones = [o for o in project['objects'] if o['type'] == 'zone']
        if len(zones) != 1 or len(project['objects']) != 1:
            ap.error('This pilot accepts exactly one zone; exclusions/points must not be silently discarded')
        src = zones[0]
        zone = dict(x=args.center[0], z=args.center[1], radius=args.radius,
                    min_y=args.height[0], max_y=args.height[1], count=src['count'],
                    kinds=src['kinds'], seed=src['seed'])
        bundle = plan_zone(meshes, zone)
        bundle.update(source_annotation_sha256=hashlib.sha256(args.project.read_bytes()).hexdigest(),
                      source_ngp_sha256=ngp_sha,
                      mapping_status='UNCALIBRATED: proposed central village zone; schematic circle not transformed')
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'draft.json').write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding='utf-8')
    create_preview(meshes, objects, bundle, args.output/'map.html')
    counts = {k: sum(p['kind'] == k for p in bundle['placements']) for k in ('message', 'blood', 'ghost')}
    print(json.dumps(dict(meshes=len(meshes), faces=sum(len(m['faces']) for m in meshes),
                          counts=counts, unplaced=bundle['unplaced'],
                          deployable=False, preview=str(args.output/'map.html')), ensure_ascii=False))


if __name__ == '__main__':
    main()
