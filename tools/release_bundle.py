"""Create the public player ZIP from explicitly selected, validated artifacts."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


def _forwarder_tool():
    path = Path(__file__).with_name('forwarder.py')
    spec = importlib.util.spec_from_file_location('release_forwarder',path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(root, nro, shader_dir, output, forwarder_dir=None):
    root,nro,shader_dir,output = map(Path,(root,nro,shader_dir,output))
    archive = Path(str(output)+'.zip')
    if output.exists() or archive.exists():
        raise ValueError('Release output already exists; choose a new directory')
    tool = _forwarder_tool()
    _,nacp = tool.read_nro_assets(nro.read_bytes())
    version = nacp[0x3060:0x3070].split(b'\0',1)[0].decode()
    guide_name = 'README.md' if forwarder_dir is not None else 'README-nro.md'
    sources = {'README.md':root/'docs/players'/guide_name,'LICENSE':root/'LICENSE',
               'THIRD_PARTY_NOTICES.md':root/'THIRD_PARTY_NOTICES.md',
               'switch/ds2scholar-nx/ds2.nro':nro}
    for name in ('sa2_shaders.mesp','sa2_shaders.mesp.idx'):
        sources['switch/ds2scholar-nx/'+name] = shader_dir/name
    for name in ('god_extract.py','extract_iso.py','stfs_extract.py'):
        sources['extract-tools/'+name] = root/'tools'/name
    tracked = subprocess.check_output(['git','-C',str(root),'ls-files','-z']).decode().split('\0')
    for name in tracked:
        if name and Path(name).name.upper().startswith(('LICENSE','LICENCE','COPYING','NOTICE','COPYRIGHT')):
            sources['licenses/'+name] = root/name
    # Preserve linked license/version notices too, without shipping source/build trees.
    notice_text = (root/'THIRD_PARTY_NOTICES.md').read_text(encoding='utf-8')
    for link in re.findall(r'\]\(([^)]+)\)',notice_text):
        if link.startswith(('sdk/','shaders/')) and link in tracked and (root/link).is_file():
            sources['licenses/'+link] = root/link
    if forwarder_dir is not None:
        forwarder_dir = Path(forwarder_dir)
        tool.verify_output(forwarder_dir)
        report = json.loads((forwarder_dir/'validation.json').read_text())
        if report['nro_sha256']!=digest(nro) or report['nro_version']!=version:
            raise ValueError('Forwarder was built for a different NRO')
        sources['switch/ds2scholar-nx/ds2scholar-forwarder.nsp'] = next(forwarder_dir.glob('*.nsp'))
        sources['build-info/forwarder-validation.json'] = forwarder_dir/'validation.json'
        for name in ('LICENSE-Forwarder-Mod.txt','LICENSE-hacBrewPack.txt'):
            sources['licenses/forwarder/'+name] = forwarder_dir/name
    for path in sources.values():
        if not path.is_file():
            raise FileNotFoundError('Missing release input: '+str(path))
    with tempfile.TemporaryDirectory(prefix='ds2-public-config-') as temp:
        config = Path(temp)/'ds2.toml'
        result = subprocess.run([sys.executable,'-I',str(root/'tools/make_public_config.py'),str(config)],
                                capture_output=True,text=True)
        if result.returncode:
            raise ValueError('Public configuration generation failed')
        sources['switch/ds2scholar-nx/ds2.toml'] = config
        output.mkdir(parents=True)
        for name,path in sources.items():
            target = output/name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,target)
    guide = (output/'README.md').read_text(encoding='utf-8')
    guide = guide.replace('(../pgo-profile.md)','(SOURCE_BUILD.md#pgo)')
    guide = guide.replace('(../rebuild.md)','(SOURCE_BUILD.md#rebuild)')
    (output/'README.md').write_text(guide,encoding='utf-8')
    def notice_link(match):
        label,link = match.groups()
        if 'licenses/'+link in sources:
            return '['+label+'](licenses/'+link+')'
        if link.startswith(('docs/','sdk/','shaders/')):
            return label+' (source repository)'
        return match.group(0)
    (output/'THIRD_PARTY_NOTICES.md').write_text(
        re.sub(r'\[([^\]]+)\]\(([^)]+)\)',notice_link,notice_text),encoding='utf-8')
    (output/'SOURCE_BUILD.md').write_text(
        '# Source and build instructions / Исходники и сборка\n\n'
        'This is the player package. Source ZIP is a file snapshot; PGO installation and public packaging require '
        'a full Git clone with the profile base revision in its history. Use the project repository, not only the ZIP.\n\n'
        'Это игровой пакет. Source ZIP — снимок файлов; установка PGO и публичная упаковка требуют полного '
        'Git-клона с исходной ревизией профиля в истории. Одного архива исходников недостаточно.\n\n'
        '## PGO\n\nGCC16.1.0; install the separate PGO ZIP before codegen. '
        'Read `docs/pgo-profile.md` in the repository. PGO is not needed to play.\n\n'
        'Профиль устанавливается до кодогена; инструкция `docs/pgo-profile.md` в репозитории. Для игры PGO не нужен.\n\n'
        '## Rebuild\n\nUse `tools/win/rebuild_switch.ps1` after initial setup. '
        'See `docs/rebuild.md`, `docs/clean-build.md`, `docs/workflow.md` in the Git clone.\n\n'
        'После настройки используйте `tools/win/rebuild_switch.ps1`; подробности в этих документах Git-клона.\n',
        encoding='utf-8')
    files = sorted(path for path in output.rglob('*') if path.is_file())
    manifest = {'version':version,'nro_sha256':digest(nro),'forwarder':forwarder_dir is not None,
                'files':{path.relative_to(output).as_posix():{'bytes':path.stat().st_size,'sha256':digest(path)} for path in files}}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    files.append(output/'manifest.json')
    (output/'SHA256SUMS.txt').write_text(''.join(digest(path)+'  '+path.relative_to(output).as_posix()+'\n' for path in sorted(files)),encoding='utf-8')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as packed:
        for path in sorted(output.rglob('*')):
            if path.is_file():
                info = zipfile.ZipInfo(path.relative_to(output).as_posix(),date_time=(1980,1,1,0,0,0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                packed.writestr(info,path.read_bytes())
    with zipfile.ZipFile(archive) as packed:
        if packed.testzip() is not None:
            raise ValueError('Release ZIP CRC check failed')
    return archive


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nro',type=Path,default=root/'out/nx_pgo/ds2.nro')
    parser.add_argument('--shader-dir',type=Path,default=root/'out/shader_light2_v2')
    parser.add_argument('--forwarder-dir',type=Path)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    try:
        if args.output is None:
            _,nacp = _forwarder_tool().read_nro_assets(args.nro.read_bytes())
            version = nacp[0x3060:0x3070].split(b'\0',1)[0].decode()
            args.output = root/'out/release'/('ds2scholar-nx-'+version)
        archive = package(root,args.nro,args.shader_dir,args.output,args.forwarder_dir)
    except (OSError,ValueError,subprocess.CalledProcessError) as error:
        parser.exit(1,str(error)+'\n')
    print(json.dumps({'zip':str(archive),'bytes':archive.stat().st_size,'sha256':digest(archive)},indent=2))


if __name__=='__main__':
    main()
