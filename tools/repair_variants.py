"""Repairs the vertex declarations of the native renderer's vertex-shader variants.

  python tools/repair_variants.py <variants folder> <out folder> <container folder> [<container folder> ...]

The renderer (sa2_shader_misses -> variants/vs_from_n<N>_<key>.bin, DumpLoadedVertexVariant in
app/src/me/me_native_system.cpp) writes a library container whose microcode is replaced by the one the ring loaded
(Direct3D permuted the vertex fetches for the bound declaration); its DECL still describes the template's order.
This finds the template (a container with the same size and the same bytes outside the microcode) and runs
shaders/tools/repair_vertex_variant_declarations.cpp (out/tools/repair_vertex_variant_declarations.exe), which proves
the permutation and writes a container for the loaded order, or refuses. Output: <out>/vs_<key>.bin.
"""
import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, 'out', 'tools', 'repair_vertex_variant_declarations.exe')


def code_range(b):
    virtual, = struct.unpack_from('>I', b, 4)
    header, = struct.unpack_from('>I', b, 24)
    off, size = struct.unpack_from('>II', b, header)
    return virtual + off, virtual + off + size


def main():
    variants, out, folders = sys.argv[1], sys.argv[2], sys.argv[3:]
    os.makedirs(out, exist_ok=True)
    templates = []
    for d in folders:
        for n in sorted(os.listdir(d)):
            if n.startswith('vs_') and n.endswith('.bin'):
                p = os.path.join(d, n)
                templates.append((p, open(p, 'rb').read()))
    ok = refused = unmatched = 0
    for n in sorted(os.listdir(variants)):
        if not n.endswith('.bin'):
            continue
        v = open(os.path.join(variants, n), 'rb').read()
        a, e = code_range(v)
        match = None
        for p, t in templates:
            if len(t) == len(v) and t[:a] == v[:a] and t[e:] == v[e:] and t[a:e] != v[a:e]:
                match = p
                break
        if not match:
            unmatched += 1
            print(f'{n}: no template')
            continue
        dst = os.path.join(out, 'vs_' + n.rsplit('_', 1)[1])
        if os.path.exists(dst):
            os.remove(dst)
        r = subprocess.run([TOOL, match, os.path.join(variants, n), dst], capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(dst):
            ok += 1
        else:
            refused += 1
            print(f'{n}: refused ({os.path.basename(match)}): {(r.stderr or r.stdout).strip()[:200]}')
    print(f'{ok} repaired, {refused} refused, {unmatched} without a template')


if __name__ == '__main__':
    main()
