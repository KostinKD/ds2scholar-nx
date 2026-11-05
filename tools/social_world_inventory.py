"""Inventory actual SotFS navigation maps without modifying game data."""
import json
import struct
from pathlib import Path
from extract_navmesh import Bxf4Archive, decompress_dcx
from social_world import read_ngp, read_msb_objects
from social_seed import network_grid


def main():
    root = Path('out/social_world/world')
    root.mkdir(parents=True, exist_ok=True)
    param = Path('out/social_world/NetworkAreaParam.param').read_bytes()
    report = []
    for number in (1, 2):
        archive = Bxf4Archive(f'assets/game_root/GameData{number}.bhd',
                              f'assets/game_root/GameData{number}.bdt')
        try:
            for name in sorted(archive.entries):
                if not name.endswith('.ngp'):
                    continue
                map_id = Path(name).stem
                area = int(map_id[1:].replace('_', ''))
                meshes = read_ngp(decompress_dcx(archive.read_file(name)))
                objects = read_msb_objects(decompress_dcx(archive.read_file(name[:-4]+'.msb')))
                vertices = [v for m in meshes for v in m['vertices']]
                bounds = [[min(v[i] for v in vertices), max(v[i] for v in vertices)] for i in range(3)]
                try:
                    grid = network_grid(param, area)
                except ValueError:
                    grid = None
                record = dict(map=map_id, area=area, grid=grid, bounds=bounds,
                              meshes=len(meshes), faces=sum(len(m['faces']) for m in meshes),
                              objects=len(objects), status='navigation-inventory-only')
                (root/(map_id+'.json')).write_text(json.dumps(dict(meshes=meshes, objects=objects)))
                report.append(record)
                print(map_id, area, record['faces'], 'grid='+str(grid), flush=True)
        finally:
            archive.close()
    (root/'inventory.json').write_text(json.dumps(report, indent=2))
    print('TOTAL', len(report))


if __name__ == '__main__':
    main()
