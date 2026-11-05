"""Build a HOME forwarder without rebuilding or embedding the game's NRO.

Metadata policy follows Prototype 2's checked Forwarder-Mod/hacBrewPack recipe.
Outputs belong in out/. Console keys must never be printed or distributed.
"""
import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tarfile
import tempfile

TITLE_ID = 0x01445332534F0000
NRO_PATH = 'sdmc:/switch/ds2scholar-nx/ds2.nro'
LOADER_COMMIT = '9853bd9167d5a7f0c5fdf935864245c1fbcf8282'
PACKER_COMMIT = '745b16ecfc9ce055743067d200572204cb2aac6c'


def bounded(data, offset, size):
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError('Truncated or out-of-bounds artifact')
    return data[offset:offset+size]


def read_nro_assets(data):
    if bounded(data, 0x10, 4) != b'NRO0':
        raise ValueError('Not an NRO')
    base = struct.unpack('<I', bounded(data, 0x18, 4))[0]
    if base < 0x80 or bounded(data, base, 4) != b'ASET':
        raise ValueError('NRO has no valid ASET')
    bounded(data, base, 0x38)
    assets = []
    ranges = []
    for position in (8, 24):
        offset, size = struct.unpack('<QQ', bounded(data, base+position, 16))
        if offset < 0x38 or not size:
            raise ValueError('NRO icon/NACP missing or overlapping ASET header')
        assets.append(bounded(data, base+offset, size))
        ranges.append((offset,offset+size))
    if max(ranges[0][0],ranges[1][0]) < min(ranges[0][1],ranges[1][1]):
        raise ValueError('NRO icon and NACP overlap')
    icon, nacp = assets
    if not icon.startswith(b'\xff\xd8') or not icon.endswith(b'\xff\xd9'):
        raise ValueError('NRO icon must be JPEG')
    if len(nacp) != 0x4000:
        raise ValueError('Unexpected NACP size')
    return icon, nacp


def make_control(nacp):
    if len(nacp) != 0x4000:
        raise ValueError('Unexpected NACP size')
    control = bytearray(nacp)
    control[0x3025] = 1  # StartupUserAccount=Required: SDK consumes preselected user.
    return bytes(control)


def validate_icon(data):
    """Check the JPEG frame format required by the HOME icon; keep the original bytes."""
    if not data.startswith(b'\xff\xd8') or not data.endswith(b'\xff\xd9'):
        raise ValueError('HOME icon must be JPEG')
    offset = 2
    while offset<len(data)-2:
        if data[offset]!=0xFF:
            raise ValueError('Invalid JPEG marker')
        while offset<len(data) and data[offset]==0xFF:
            offset += 1
        marker = bounded(data,offset,1)[0]
        offset += 1
        if marker in (0xD8,0xD9,0x01) or 0xD0<=marker<=0xD7:
            continue
        length = struct.unpack('>H',bounded(data,offset,2))[0]
        if length<2:
            raise ValueError('Invalid JPEG segment size')
        segment = bounded(data,offset+2,length-2)
        if marker in (0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF):
            if marker!=0xC0 or len(segment)!=15 or segment[0]!=8:
                raise ValueError('HOME icon must be baseline 8-bit RGB JPEG')
            height,width,channels = struct.unpack('>HHB',segment[1:6])
            if (width,height,channels)!=(256,256,3):
                raise ValueError('HOME icon must be 256x256 RGB')
            return data
        if marker==0xDA:
            break
        offset += length
    raise ValueError('JPEG has no supported frame header')


def loader_config(template, title_id=TITLE_ID, max_cpu=3):
    if not 0x0100000000000000 <= title_id <= 0x01FFFFFFFFFFFFFF or title_id & 0xFFF:
        raise ValueError('Title ID must be an application base ID ending in 000')
    if max_cpu not in (2,3):
        raise ValueError('CPU limit must be 2 or 3')
    result = copy.deepcopy(template)
    result.update(name='ds2scholar', address_space_type=3, is_64_bit=True)
    for name in ('title_id','title_id_range_min','title_id_range_max',
                 'program_id','program_id_range_min','program_id_range_max'):
        result[name] = f'0x{title_id:016X}'
    capabilities = result.get('kernel_capabilities',[])
    cores = [entry for entry in capabilities if entry['type']=='kernel_flags']
    types = [entry for entry in capabilities if entry['type']=='application_type']
    if len(cores)!=1 or len(types)!=1:
        raise ValueError('Expected one core descriptor and one application type')
    cores[0]['value'].update(lowest_cpu_id=0,highest_cpu_id=max_cpu)
    types[0]['value'] = 1  # Application rather than library applet.
    for entry in capabilities:
        if entry['type']=='debug_flags':
            entry['value'] = {'allow_debug':False,'force_debug':True,'force_debug_prod':False}
    return result


def check_npdm(data, title_id=TITLE_ID, max_cpu=3):
    if bounded(data,0,4)!=b'META' or not (bounded(data,0xC,1)[0]&1):
        raise ValueError('Not a 64-bit META')
    if (data[0xC]>>1)&7 != 3:
        raise ValueError('NPDM must request 39-bit address space')
    result = {'title_id':f'{title_id:016X}','address_space_bits':39}
    for label,position,kernel_offset,kernel_size in (
            ('ACI0',0x70,0x30,0x34),('ACID',0x78,0x230,0x234)):
        start, size = struct.unpack('<II',bounded(data,position,8))
        section = bounded(data,start,size)
        magic_offset = 0 if label=='ACI0' else 0x200
        if bounded(section,magic_offset,4)!=label.encode():
            raise ValueError('Missing '+label)
        ids = struct.unpack('<Q',bounded(section,0x10,8)) if label=='ACI0' else struct.unpack('<QQ',bounded(section,0x210,16))
        if any(value!=title_id for value in ids):
            raise ValueError('Wrong '+label+' program ID')
        offset = struct.unpack('<I',bounded(section,kernel_offset,4))[0]
        length = struct.unpack('<I',bounded(section,kernel_size,4))[0]
        if length%4:
            raise ValueError('Invalid capability size')
        flags = [item[0] for item in struct.iter_unpack('<I',bounded(section,offset,length)) if item[0]&15==7]
        if len(flags)!=1:
            raise ValueError('Expected one '+label+' core capability')
        value = flags[0]
        cpus = [(value>>16)&255,(value>>24)&255]
        priorities = sorted([(value>>4)&63,(value>>10)&63])
        if cpus!=[0,max_cpu] or not priorities[0]<=59<=priorities[1]:
            raise ValueError('Wrong '+label+' CPU/priority range')
        result[label] = {'cpu_range':cpus,'priority_range':priorities}
    return result


def prepare(nro_data, loader_dir, stage, title_id=TITLE_ID, max_cpu=3, icon_data=None):
    icon, nacp = read_nro_assets(nro_data)
    if icon_data is not None:
        icon = validate_icon(icon_data)
    config = loader_config(json.loads((loader_dir/'hbl.json').read_text()),title_id,max_cpu)
    (loader_dir/'hbl.json').write_text(json.dumps(config,indent=2)+'\n')
    (stage/'control').mkdir(parents=True,exist_ok=True)
    (stage/'romfs').mkdir(parents=True,exist_ok=True)
    (stage/'control/icon_AmericanEnglish.dat').write_bytes(icon)
    (stage/'control/control.nacp').write_bytes(make_control(nacp))
    for name in ('nextNroPath','nextArgv'):
        (stage/'romfs'/name).write_text(NRO_PATH,encoding='utf-8',newline='\n')
    return nacp[0x3060:0x3070].split(b'\0',1)[0].decode('utf-8')


def packing_keys(text):
    required = {'header_key':64,'key_area_key_application_00':32}
    found = {}
    for line in text.splitlines():
        name, sep, value = line.partition('=')
        name, value = name.strip(), value.strip()
        if sep and name in required:
            if name in found or not re.fullmatch('[0-9a-fA-F]{'+str(required[name])+'}',value):
                raise ValueError('Invalid or duplicate packing key: '+name)
            found[name] = value
    if set(found)!=set(required):
        raise ValueError('Missing header_key or key_area_key_application_00')
    return ''.join(name+' = '+found[name]+'\n' for name in required)


def pack_nsp(packer, keys_path, stage, output, title_id=TITLE_ID):
    minimal = packing_keys(keys_path.read_text(encoding='utf-8-sig'))
    output.mkdir(parents=True,exist_ok=True)
    if (output/f'{title_id:016x}.nsp').exists() or (output/f'{title_id:016X}.nsp').exists():
        raise ValueError('NSP output already exists')
    # Only a throwaway file is passed to the packer; never capture raw key-bearing output in a log.
    with tempfile.TemporaryDirectory(prefix='packing-',dir=stage.parent) as secret_dir:
        secret = Path(secret_dir).resolve()
        if secret.parent!=stage.parent.resolve():
            raise ValueError('Unexpected private temporary directory')
        key_file = secret/'packing.keys'
        descriptor = os.open(key_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'w',encoding='ascii') as stream:
            stream.write(minimal)
        result = subprocess.run([str(packer),'--titleid',f'{title_id:016X}',
            '-k',str(key_file),'--nologo','--keygeneration','1','--nspdir',str(output)],
            cwd=stage,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f'hacBrewPack failed (exit {result.returncode}); output suppressed to protect keys')
    paths = list(output.glob('*.nsp'))
    if len(paths)!=1:
        raise ValueError('Packer did not produce exactly one NSP')
    return paths[0]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_nsp(data):
    if bounded(data,0,4)!=b'PFS0':
        raise ValueError('NSP must be a PFS0 container')
    count, string_size = struct.unpack('<II',bounded(data,4,8))
    if count!=3:
        raise ValueError('Expected program, control and metadata NCAs only')
    string_start = 16+count*24
    strings = bounded(data,string_start,string_size)
    payload = string_start+string_size
    result = []
    ranges = []
    for index in range(count):
        offset,size,name_offset,reserved = struct.unpack('<QQII',bounded(data,16+index*24,24))
        if name_offset>=len(strings) or b'\0' not in strings[name_offset:]:
            raise ValueError('Invalid NSP filename offset')
        name = strings[name_offset:].split(b'\0',1)[0].decode('ascii')
        if not re.fullmatch(r'[0-9a-fA-F]{32}(?:\.cnmt)?\.nca',name):
            raise ValueError('NSP contains an unexpected file')
        chunk = bounded(data,payload+offset,size)
        if not size or reserved or any(max(offset,a)<min(offset+size,b) for a,b in ranges):
            raise ValueError('Empty or overlapping NSP files')
        if name in [entry['name'] for entry in result]:
            raise ValueError('Duplicate NSP file')
        ranges.append((offset,offset+size))
        result.append({'name':name,'bytes':size,'sha256':hashlib.sha256(chunk).hexdigest()})
    return result


def verify_output(output, max_cpu=3, title_id=TITLE_ID):
    paths = list(output.glob('*.nsp'))
    if len(paths)!=1:
        raise ValueError('Expected exactly one NSP')
    npdm = check_npdm((output/'main.npdm').read_bytes(),title_id,max_cpu)
    control = (output/'control.nacp').read_bytes()
    if len(control)!=0x4000 or control[0x3025]!=1:
        raise ValueError('Invalid NACP user-selection policy')
    report = json.loads((output/'validation.json').read_text())
    if report['nsp_sha256']!=sha(paths[0]) or report['nro_path']!=NRO_PATH:
        raise ValueError('NSP checksum or target does not match the report')
    if 'icon_sha256' in report:
        icon = (output/'icon.jpg').read_bytes()
        if hashlib.sha256(icon).hexdigest()!=report['icon_sha256']:
            raise ValueError('Icon checksum mismatch')
        if report.get('custom_icon'):
            validate_icon(icon)
    for line in (output/'SHA256SUMS.txt').read_text().splitlines():
        expected,name = line.split('  ',1)
        if Path(name).name!=name or sha(output/name)!=expected:
            raise ValueError('Release checksum mismatch')
    return {'npdm':npdm,'nsp_files':check_nsp(paths[0].read_bytes()),'checksums':'passed'}


def msys_path(path):
    # Keep a caller's no-space junction: resolving G:/devkitPro introduces Program Files.
    path = Path(os.path.abspath(path)).as_posix()
    if len(path)>2 and path[1]==':':
        return '/'+path[0].lower()+path[2:]
    return path


def ensure_source(path, url, revision):
    if not path.exists():
        path.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['git','clone','--no-checkout',url,str(path)],check=True)
        subprocess.run(['git','-C',str(path),'checkout','--detach',revision],check=True)
    actual = subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip()
    dirty = subprocess.check_output(['git','-C',str(path),'status','--porcelain','--untracked-files=no'],text=True).strip()
    if actual!=revision or dirty:
        raise ValueError('Dependency must be clean and at pinned revision: '+str(path))


def export_source(source, target, revision):
    # Export the committed tree, not a directory that could contain stale .o or extra source files.
    data = subprocess.check_output(['git','-C',str(source),'archive','--format=tar',revision])
    target.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(data),mode='r:') as archive:
        archive.extractall(target,filter='data')


def build(args):
    nro_data = args.nro.read_bytes()
    read_nro_assets(nro_data)
    icon_data = validate_icon(args.icon.read_bytes()) if args.icon else None
    if not args.keys.is_file():
        raise ValueError('Set --keys or SWITCH_PROD_KEYS to your local prod.keys')
    packing_keys(args.keys.read_text(encoding='utf-8-sig'))
    args.output.mkdir(parents=True,exist_ok=True)
    if any(args.output.iterdir()):
        raise ValueError('Use an empty output directory; existing release files are not replaced')
    for name,url,revision in (
            ('loader','https://github.com/Skywalker25/Forwarder-Mod.git',LOADER_COMMIT),
            ('packer','https://github.com/rlaphoenix/hacBrewPack.git',PACKER_COMMIT)):
        ensure_source(args.deps/name,url,revision)
    work_root = args.output.parent/'forwarder-work'
    work_root.mkdir(parents=True,exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='build-',dir=work_root)).resolve()
    for name in ('loader','packer'):
        export_source(args.deps/name,work/name,LOADER_COMMIT if name=='loader' else PACKER_COMMIT)
    version = prepare(nro_data,work/'loader',work,args.title_id,args.max_cpu,icon_data=icon_data)
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}',version):
        raise ValueError('NRO version is not safe for an output filename')
    main_c = work/'loader/source/main.c'
    source = main_c.read_text()
    if source.count('void NORETURN ')!=1:
        raise ValueError('Unexpected pinned loader noreturn declaration')
    main_c.write_text(source.replace('void NORETURN ','void __attribute__((noreturn)) '))
    shutil.copyfile(work/'packer/config.mk.template',work/'packer/config.mk')
    env = os.environ.copy()
    env.update(DEVKITPRO=msys_path(args.devkitpro),FWD_LOADER=msys_path(work/'loader'),
               FWD_PACKER=msys_path(work/'packer'),MSYSTEM='MINGW64')
    shell = args.msys/'usr/bin/bash.exe'
    for command in (
            'make -C "$FWD_LOADER" -j2 RELEASE=1 ROMFS=',
            'make -C "$FWD_PACKER" -j2'):
        subprocess.run([str(shell),'--noprofile','--norc','-c',
            'export PATH="/mingw64/bin:/usr/bin:$DEVKITPRO/devkitA64/bin:$DEVKITPRO/tools/bin:$PATH"; '+command],
            env=env,check=True)
    exe = '.exe' if os.name=='nt' else ''
    exefs = work/'exefs'
    exefs.mkdir()
    tools = args.devkitpro/'tools/bin'
    subprocess.run([str(tools/('elf2nso'+exe)),str(work/'loader/hbl.elf'),str(exefs/'main')],check=True)
    subprocess.run([str(tools/('npdmtool'+exe)),str(work/'loader/hbl.json'),str(exefs/'main.npdm')],check=True)
    report = check_npdm((exefs/'main.npdm').read_bytes(),args.title_id,args.max_cpu)
    if (work/'control/control.nacp').read_bytes()[0x3025]!=1:
        raise ValueError('User selection was not enabled')
    for name in ('nextNroPath','nextArgv'):
        if (work/'romfs'/name).read_text()!=NRO_PATH:
            raise ValueError('Unexpected forwarder target')
    packer = work/'packer'/('hacbrewpack'+exe)
    nsp = pack_nsp(packer,args.keys,work,args.output,args.title_id)
    # The packer signs/patches NPDM in place: validate again after it has run.
    report = check_npdm((exefs/'main.npdm').read_bytes(),args.title_id,args.max_cpu)
    nsp_files = check_nsp(nsp.read_bytes())
    final = args.output/f'ds2scholar-forwarder-{version}-core{args.max_cpu}.nsp'
    nsp.rename(final)
    report.update(nro_path=NRO_PATH,nro_version=version,nro_sha256=hashlib.sha256(nro_data).hexdigest(),
                  startup_user_account='Required',loader_commit=LOADER_COMMIT,packer_commit=PACKER_COMMIT,
                  nsp_bytes=final.stat().st_size,nsp_sha256=sha(final),nsp_files=nsp_files,console_test='not run',
                  custom_icon=icon_data is not None,icon_sha256=sha(work/'control/icon_AmericanEnglish.dat'))
    shutil.copyfile(exefs/'main.npdm',args.output/'main.npdm')
    shutil.copyfile(work/'control/control.nacp',args.output/'control.nacp')
    shutil.copyfile(work/'control/icon_AmericanEnglish.dat',args.output/'icon.jpg')
    shutil.copyfile(work/'loader/LICENSE.md',args.output/'LICENSE-Forwarder-Mod.txt')
    shutil.copyfile(work/'packer/LICENSE',args.output/'LICENSE-hacBrewPack.txt')
    (args.output/'validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    (args.output/'README.txt').write_text(
        'DS2 SotFS HOME forwarder\nInstall the NSP, then launch from HOME.\n'
        'Keep /switch/ds2scholar-nx/ds2.nro and the game folder on SD.\n'
        'NPDM: 39-bit, cores 0-'+str(args.max_cpu)+'. Game thread affinity is unchanged.\n'
        'User selection is required; saves and online identity use the selected Switch user.\n'
        'No replacement of atmosphere/hbl.nsp is needed. Console launch is not yet verified.\n',encoding='utf-8')
    deliverables = sorted(p for p in args.output.iterdir() if p.is_file())
    (args.output/'SHA256SUMS.txt').write_text(''.join(sha(p)+'  '+p.name+'\n' for p in deliverables),encoding='ascii')
    print(json.dumps(report,indent=2))
    print('Built '+str(final))


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nro',type=Path,default=root/'out/nx_pgo/ds2.nro')
    parser.add_argument('--keys',type=Path,default=Path(os.environ.get('SWITCH_PROD_KEYS','prod.keys')))
    parser.add_argument('--deps',type=Path,default=root/'out/forwarder-deps')
    parser.add_argument('--output',type=Path,default=root/'out/forwarder')
    parser.add_argument('--devkitpro',type=Path,default=Path(os.environ.get('DEVKITPRO','G:/devkitPro')))
    parser.add_argument('--msys',type=Path,default=Path(os.environ.get('MSYS2_ROOT','G:/msys64')))
    parser.add_argument('--title-id',type=lambda value:int(value,16),default=TITLE_ID)
    parser.add_argument('--max-cpu',type=int,choices=(2,3),default=3)
    parser.add_argument('--icon',type=Path,help='Optional 256x256 baseline RGB JPEG for the HOME tile')
    parser.add_argument('--verify-output',type=Path,help='Verify an existing build; no keys or compilation needed')
    args = parser.parse_args()
    for name in ('nro','keys','deps','output','devkitpro','msys'):
        path = getattr(args,name)
        setattr(args,name,Path(os.path.abspath(path)) if name in ('devkitpro','msys') else path.resolve())
    if args.icon:
        args.icon = args.icon.resolve()
    try:
        if args.verify_output:
            print(json.dumps(verify_output(args.verify_output.resolve(),args.max_cpu,args.title_id),indent=2))
        else:
            build(args)
    except (OSError,ValueError,RuntimeError,subprocess.CalledProcessError) as error:
        parser.exit(1,str(error)+'\n')


if __name__=='__main__':
    main()
