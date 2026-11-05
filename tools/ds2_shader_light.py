"""Build opt-in SotFS shader experiments from locally generated HLSL.

Inputs and outputs contain game data and stay under out/. No generated HLSL in git.
Container identities: ds2_049/075 (n31/385/421/961), ds2_087/091 (n95/1255).
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess

TARGETS = {
    '04762adf6a086695': 1,
    '3c14b756c88a2b7f': 2,
    '41db93b1dec497de': 4,
    '9942495d3b412155': 8,
    '0feaa33b192cdc87': 16,
    'caee55f06defe9d8': 16,
}
# Generated v8 HLSL, normalized to LF by read_text. Refuse a different translator
# output until its register-level patch sites have been audited again.
SOURCE_SHA256 = {
    '04762adf6a086695': '6defdacf8d77afcb2bbaf1f2b9c745e9d84466a855c09bf3fba4b6d759330b0b',
    '3c14b756c88a2b7f': 'bb5662a10e54d3c3120cb82085149acb83c6a35cacee5e2ae67501cf975cc135',
    '41db93b1dec497de': 'e8123894389d26e834f45ffab5497b271e09e78cc362b2dc3302a1a04657f001',
    '9942495d3b412155': '133e6b6a9d3a442182bf48deae2239a3ee26efee8caa1da50d3f5eef5b250c13',
    '0feaa33b192cdc87': '79b7f0c54a48f2f587c71b08c339c71e9b52851a587011c4d7228706bdff0aea',
    'caee55f06defe9d8': '56529f301d72357c30f76fb2aea5ff788036fef90b1dadc210d799b138b8f574',
}


def transform(key, source):
    if key not in TARGETS or 'DS2_SHADER_LIGHT' in source:
        raise ValueError('unknown shader or source already transformed')
    if key == '0feaa33b192cdc87':
        # PS95: first diffuse and material channel, without the TEXCOORD7.w
        # blend. Unlike 0 * second_layer, this can eliminate the second fetches.
        material = 'r3.w = r3.y * r7.w + r3.x;'
        if source.count(material) != 1:
            raise ValueError(f'{key}: expected one material-channel blend')
        source = source.replace(material, branch('r3.w = r3.x;', material))
        for dest, texture in (('r9.xyz', 'g_DiffuseMap2'), ('r0.z', 'g_BumpMap2')):
            fetch = re.escape(dest) + r' = tfetch2D\(' + texture + r'_[^;]+;'
            source, count = re.subn(fetch, lambda m: branch(dest + ' = 0.0;', m[0]), source)
            if count != 1:
                raise ValueError(f'{key}: expected one {texture} fetch, found {count}')
        pattern = re.escape('r2.xyzw = r9.xyzw * r7.wwww + r2.xyzw;')
        replacement = lambda m: branch('r2.xyzw = r2.xyzw;', m[0])
    elif key == 'caee55f06defe9d8':
        # PS1255: keep the first reconstructed normal before normalization.
        # Dither, alpha and final encoding are unchanged. Shares mask16 with PS95.
        pattern = re.escape('r0.yzw = r0.xzy * r7.www + r2.xzy;')
        replacement = lambda m: branch('r0.yzw = r2.xzy;', m[0])
        fetch = r'r9\.xyz = tfetch2D\(g_BumpMap2_[^;]+;'
        source, count = re.subn(fetch, lambda m: branch('r9.xyz = 0.0;', m[0]), source)
        if count != 1:
            raise ValueError(f'{key}: expected one second-normal fetch, found {count}')
    elif key == '04762adf6a086695':
        # Keep the first flipbook frame and its alpha; avoid the second fetch/lerp.
        pattern = r'if \(p0\)\s*\{\s*r5\.xyzw = tfetch2D\(DiffuseSampler_[^}]+\}'
        replacement = lambda m: '[branch] if (!DS2_SHADER_LIGHT)\n\t{\n' + m[0] + '\n\t}'
    elif key == '3c14b756c88a2b7f':
        # Distance and height fog stay. Only remove the final log/exp shaping curve.
        pattern = (r'ps = clamp\(log2\(abs\(r0\.x\)\), FLT_MIN, FLT_MAX\);'
                   r'.*?ps = exp2\(r0\.x\);')
        light = ('r1.xyz = FC_PrecisionParam.xxx * FC_FinalColorMult.xyz;\n'
                 '\tr2.xyz = -r0.yzw + FC_FogCol.xyz;\n\tps = saturate(r0.x);')
        replacement = lambda m: branch(light, m[0])
    elif key == '41db93b1dec497de':
        # Input r0 is already 2 * premultiplied texel * vertex tint. Use modulate
        # rather than overlay; alpha and the later atmosphere/exposure stay.
        pattern = re.escape('r0.xyz = select(r7.xyz == 0.0, r6.xyz, r0.xyz);')
        replacement = lambda m: branch('r0.xyz *= 0.5;', m[0])
    else:
        # Blend weight zero means first diffuse/bump/specular layer. DCE can remove
        # the second layer's three samples and the blend-map sample after specializing.
        pattern = re.escape('r9.x = saturate(select(r4.w > 0.0, r4.z, r4.x));')
        replacement = lambda m: branch('r9.x = 0.0;', m[0])
        # Explicitly gate the fetches too. A zero blend weight alone does not let
        # DXC remove them (0 * NaN is still NaN). This is a quality variant, so
        # use finite dummy values for the unused layer, with its weight zero.
        for dest, texture in (('r8.y', 'g_BumpMap2'), ('r8.zw', 'g_SpecularMap2'),
                              ('r11.xyz', 'g_DiffuseMap2'), ('r0.x', 'g_BlendMap')):
            fetch = re.escape(dest) + r' = tfetch2D\(' + texture + r'_[^;]+;'
            source, count = re.subn(fetch, lambda m: branch(dest + ' = 0.0;', m[0]), source)
            if count != 1:
                raise ValueError(f'{key}: expected one {texture} fetch, found {count}')
    patched, n = re.subn(pattern, replacement, source, flags=re.DOTALL)
    if n != 1:
        raise ValueError(f'{key}: expected one patch site, found {n}')
    return ('// ds2scholar-nx: opt-in light variant, renderer SpecId 0 bit 23.\n'
            '#ifdef DS2_SHADER_LIGHT_FORCE\n'
            '#define DS2_SHADER_LIGHT (DS2_SHADER_LIGHT_FORCE != 0)\n'
            '#else\n'
            '#define DS2_SHADER_LIGHT ((g_SpecConstants() & (1u << 23)) != 0)\n'
            '#endif\n' + patched)


def branch(light, original):
    return ('[branch] if (DS2_SHADER_LIGHT)\n\t{\n\t' + light +
            '\n\t}\n\telse\n\t{\n\t' + original + '\n\t}')


def instructions(path):
    data = path.read_bytes()
    if len(data) % 4:
        raise ValueError('unaligned SPIR-V')
    words = struct.unpack(f'<{len(data)//4}I', data)
    if len(words) < 5 or words[0] != 0x07230203:
        raise ValueError('invalid SPIR-V')
    ops = collections.Counter()
    i = 5
    while i < len(words):
        size, op = words[i] >> 16, words[i] & 65535
        if not size or i + size > len(words):
            raise ValueError('truncated SPIR-V instruction')
        ops[op] += 1
        i += size
    return {'bytes': len(data), 'instructions': sum(ops.values()),
            'image_samples': sum(ops[op] for op in range(87, 98)),
            'ext_inst': ops[12], 'ops': dict(sorted(ops.items()))}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--inputs', type=Path, default=Path('out/shaders'))
    ap.add_argument('--base', type=Path, default=Path('out/nx/keep/shaders_v8.mesp'))
    ap.add_argument('--output', type=Path, required=True, help='new directory; never overwrites inputs')
    ap.add_argument('--dxc', type=Path, default=Path('out/tools/dxc/bin/x64/dxc.exe'))
    ap.add_argument('--packer', type=Path, default=Path('out/shaders/bin/me_pack_shaders.exe'))
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    for part in ('hlsl', 'in', 'spirv', 'check'):
        (a.output / part).mkdir()
    report = {}
    for key, bit in TARGETS.items():
        stem = 'ps_' + key
        original = a.inputs / 'hlsl' / (stem + '.hlsl')
        text = original.read_text(encoding='utf-8')
        digest = hashlib.sha256(text.encode()).hexdigest()
        if digest != SOURCE_SHA256[key]:
            raise ValueError(f'{key}: source changed, audit it before updating SOURCE_SHA256')
        patched = a.output / 'hlsl' / original.name
        patched.write_text(transform(key, text), encoding='utf-8')
        shutil.copy2(a.inputs / 'in' / (stem + '.bin'), a.output / 'in')
        modes = {}
        for mode, source, defines in (
                ('original', original, []),
                ('off', patched, ['-D', 'DS2_SHADER_LIGHT_FORCE=0']),
                ('on', patched, ['-D', 'DS2_SHADER_LIGHT_FORCE=1']),
                ('spec', patched, [])):
            dest = (a.output / 'spirv' / (stem + '.spv') if mode == 'spec' else
                    a.output / 'check' / (stem + '_' + mode + '.spv'))
            subprocess.run([str(a.dxc.resolve()), '-spirv', '-T', 'ps_6_6', '-E', 'main',
                            '-HV', '2021', '-fspv-target-env=vulkan1.2', '-fvk-use-dx-layout',
                            '-Werror=parameter-usage', *defines, '-Fo', str(dest), str(source)], check=True)
            modes[mode] = instructions(dest)
        # Off must compile to the same op histogram; runtime/visual A/B remains necessary.
        if modes['original']['ops'] != modes['off']['ops']:
            raise ValueError(f'{key}: forced-off instruction histogram changed')
        if modes['on']['instructions'] >= modes['original']['instructions']:
            raise ValueError(f'{key}: light variant did not reduce SPIR-V instructions')
        if bit in (1, 8, 16) and modes['on']['image_samples'] >= modes['original']['image_samples']:
            raise ValueError(f'{key}: expected texture sample reduction did not happen')
        print(f"{stem} bit={bit}: original/off/on instructions "
              f"{modes['original']['instructions']}/{modes['off']['instructions']}/{modes['on']['instructions']}; "
              f"samples {modes['original']['image_samples']} -> {modes['on']['image_samples']}", flush=True)
        report[key] = {'mask': bit, 'source_sha256': digest, 'modes': modes}
    (a.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    subprocess.run([str(a.packer.resolve()), '--replace-exact', str(a.base), str(a.output / 'in'),
                    str(a.output / 'spirv'), str(a.output / 'sa2_shaders.mesp')], check=True)


if __name__ == '__main__':
    main()
