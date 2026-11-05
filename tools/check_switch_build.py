#!/usr/bin/env python3
"""Checks a Switch build before it is packaged (from sasrt-nx's check_switch_build.py and nfsmw-nx's lessons).

  python tools/check_switch_build.py [--elf out/nx/ds2] [--nro out/nx/ds2.nro]

For a controlled A/B build, --reference-elf uses the console-tested reference's guest halt functions and vector
FMA counts instead of the inherited SA2 assumptions. New halt functions or additional vector FMAs still fail.
--require-fewer-frame-pointers also requires a reduction in guest functions with an x29 frame chain.

Checks (exit 1 if any fails):
  - _start is at address 0 (nfsmw-nx: a section-ordering file that moved the start-up code made the NRO unbootable);
  - the build names the optimised codegen flavour (the only one delivered);
  - the NRO links the nfsmw NVK driver of the SDK (its "Mesa x.y.z" string; the generic portlibs Mesa once got in);
  - branch-to-self loops in recompiled functions are only in the functions with a known guest halt (KNOWN_HALTS; a
    polling loop GCC turned into "b ." with non-volatile memory means a missing loop barrier);
  - no vector fmla/fmls in recompiled functions: the generated code has no vector fused multiply-add (VMX multiply-adds
    are a multiply and an add), so any would be contraction that leaked past -ffp-contract=off (e.g. at an LTO link).
    Scalar fmadd/fmsub/fnmadd/fnmsub come from the guest's own std::fma and are only counted.
"""
import argparse
import collections
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# SotFS (2026-10-21): ds2-nx's halts translated by masked signature (each the only match): sub_82B11CB8 ->
# sub_82B41518, sub_82BE8748 -> sub_82C187B8, sub_82C3FAA0 -> sub_82C6F9D0, sub_82DE5A18 -> sub_82E15628; plus
# sub_8292C568 (= ds2-nx sub_828FC278, listed in ds2-nx's first, classic NRO): the guest loop 0x8292C7E0-0x8292C7F0
# (stfsu f0,4(r10); lwz r9,0(r29); cmpwi cr6,r9,0; bgt) tests only *r29, which its body does not write; entered with
# *r29 > 0 it never ends on the Xbox either, and GCC turns it into "b ." (classic codegen, no loop barriers).
KNOWN_HALTS = ['sub_82B41518', 'sub_82C187B8', 'sub_82C6F9D0', 'sub_82E15628', 'sub_8292C568']
# The game's own fmadds that GCC vectorises (ds2-nx entry 33: sub_82C31A30, 2 vector fmla) = SotFS sub_82C61958.
# Used when no --reference-elf is given.
KNOWN_VECTOR_FMA = {'sub_82C61958': 2,
                    # Optimised codegen (2026-10-21): sub_82629820 has 70 guest fmadds/fnmsubs (std::fma each); with
                    # the registers as locals GCC packs 6 of them into vector fmla - the guest's own fused operations.
                    'sub_82629820': 6}
DEVKITA64 = next((d + '/devkitA64/bin/' for d in (os.environ.get('DEVKITPRO', ''), 'C:/devkitPro', '/opt/devkitpro')
                  if d and os.path.isdir(d + '/devkitA64/bin')), 'C:/devkitPro/devkitA64/bin/')
EXE = '.exe' if os.name == 'nt' else ''


def generated_calls():
    """name -> the recompiled functions its generated C++ body calls directly (app/generated/*/ *_recomp.*.cpp)."""
    import glob
    out = {}
    head = re.compile(r'^DEFINE_REX_FUNC\((sub_[0-9A-F]{8})\) \{$', re.M)
    call = re.compile(r'\b(?:__imp__)?(sub_[0-9A-F]{8})\(ctx, base\)')
    for path in glob.glob(os.path.join(ROOT, 'app', 'generated', '*', '*_recomp.*.cpp')):
        text = open(path, encoding='utf-8', errors='replace').read()
        heads = list(head.finditer(text))
        for i, m in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            out[m.group(1)] = set(call.findall(text, m.end(), end))
    return out


def chain_to(calls, f, targets, depth=4, seen=()):
    """The shortest-first chain of direct calls from f to one of the targets, at most `depth` calls long, or None."""
    callees = calls.get(f, set())
    hit = sorted(callees & targets)
    if hit:
        return [f, hit[0]]
    if depth > 1:
        for c in sorted(callees):
            if c not in seen:
                rest = chain_to(calls, c, targets, depth - 1, seen + (f,))
                if rest:
                    return [f] + rest
    return None


def scan_guest_code(elf):
    proc = subprocess.Popen([DEVKITA64 + 'aarch64-none-elf-objdump' + EXE, '-d', '--no-show-raw-insn', elf],
                            stdout=subprocess.PIPE, text=True, errors='replace', bufsize=1 << 20)
    function = None
    self_loops = []
    vector_fma = collections.Counter()
    scalar_fma = 0
    frame_functions = set()
    head = re.compile(r'^[0-9a-f]+ <([^>]+)>:$')
    instruction = re.compile(r'^\s+([0-9a-f]+):\s+(\S+)\s*(.*)$')
    for line in proc.stdout:
        match = head.match(line)
        if match:
            function = match.group(1).removeprefix('__imp__')
            continue
        match = instruction.match(line)
        if not match or not function or not function.startswith('sub_8'):
            continue
        address, operation, arguments = match.groups()
        if operation == 'b' and arguments.split(' ')[0] == address:
            self_loops.append(function)
        elif operation in ('fmla', 'fmls'):
            vector_fma[function] += 1
        elif operation in ('fmadd', 'fmsub', 'fnmadd', 'fnmsub'):
            scalar_fma += 1
        elif operation == 'mov' and arguments.replace(' ', '') == 'x29,sp':
            frame_functions.add(function)
    if proc.wait() != 0:
        sys.exit(f'objdump failed for {elf}')
    return self_loops, vector_fma, scalar_fma, frame_functions


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--elf', default=os.path.join(ROOT, 'out', 'nx', 'ds2'))
    ap.add_argument('--nro', default=os.path.join(ROOT, 'out', 'nx', 'ds2.nro'))
    ap.add_argument('--reference-elf', help='console-tested ELF whose existing guest halts and vector FMAs are accepted')
    ap.add_argument('--require-fewer-frame-pointers', action='store_true')
    ap.add_argument('--halts', default=','.join(KNOWN_HALTS),
                    help='the recompiled functions with a genuine guest halt (b . in the original PowerPC code)')
    ap.add_argument('--flavor', choices=('optimised', 'classic'), default='optimised',
                    help='the codegen flavour the NRO must name (classic: SotFS\'s first NRO, as ds2-nx\'s first)')
    ap.add_argument('--sdk-vulkan', default='C:/devkitPro/mesa-switch-main-nfsmw-source/mesa-switch-main/'
                    'mesa-unified-install/opt/devkitpro/portlibs/switch/lib/libvulkan.a')
    a = ap.parse_args()
    if a.require_fewer_frame_pointers and not a.reference_elf:
        ap.error('--require-fewer-frame-pointers requires --reference-elf')
    failures = []

    nm = subprocess.run([DEVKITA64 + 'aarch64-none-elf-nm' + EXE, a.elf], capture_output=True, text=True,
                        check=True).stdout
    start = next((int(l.split()[0], 16) for l in nm.splitlines() if l.endswith(' _start')), None)
    print(f'_start at {start:#x}' if start is not None else '_start not found')
    if start != 0:
        failures.append('_start is not at address 0')

    nro = open(a.nro, 'rb').read()
    if f'{a.flavor} codegen'.encode() not in nro:
        failures.append(f'the NRO does not name the {a.flavor} codegen flavour')
    else:
        print(f'flavour: {a.flavor} codegen')
    mesa = sorted(set(re.findall(rb'Mesa \d+\.\d+\.\d+ \(git-[0-9a-f]+\)', nro)))
    sdk = sorted(set(re.findall(rb'Mesa \d+\.\d+\.\d+ \(git-[0-9a-f]+\)', open(a.sdk_vulkan, 'rb').read())))
    print('Mesa in the NRO:', [m.decode() for m in mesa], '| in the SDK:', [m.decode() for m in sdk])
    if not mesa or mesa != sdk:
        failures.append('the NRO does not carry the SDK driver\'s Mesa string')

    self_loops, vector_fma, scalar_fma, frame_functions = scan_guest_code(a.elf)
    known = set(a.halts.split(','))
    allowed_vector_fma = collections.Counter(KNOWN_VECTOR_FMA)
    if a.reference_elf:
        reference_loops, allowed_vector_fma, _, reference_frames = scan_guest_code(a.reference_elf)
        known = set(reference_loops)
        print(f'reference guest halt functions: {", ".join(sorted(known)) or "none"}')
        print(f'guest functions with frame pointers: {len(reference_frames)} -> {len(frame_functions)}')
        if a.require_fewer_frame_pointers and len(frame_functions) >= len(reference_frames):
            failures.append('the experiment did not reduce guest functions with frame pointers')
    functions = {f.replace('__imp__', '') for f in self_loops}
    unknown = sorted(functions - known)
    # Round 7: GCC may inline a known halt into a caller (non_volatile_as_local made the callees smaller: the halts of
    # sub_828DB988 and sub_8293FA08 then appear in sub_828D71E8 and sub_8293FE28), and with a higher inline limit
    # that caller into its own caller (sub_828C5D60 inlines sub_828D71E8). A function whose generated body reaches
    # a known-halt function through at most four direct calls is accepted, and named with the chain.
    inlined = []
    if unknown:
        calls = generated_calls()
        for f in list(unknown):
            chain = chain_to(calls, f, known)
            if chain:
                inlined.append(f'{f} (inlines {" -> ".join(chain[1:])})')
                unknown.remove(f)
    print(f'branch-to-self in recompiled functions: {len(self_loops)} instructions in {len(functions)} functions, '
          f'{len(functions & known)} of them known guest halts'
          + (f'; {len(inlined)} more calling one that GCC inlined: {"; ".join(inlined)}' if inlined else ''))
    if unknown:
        failures.append('branch-to-self outside the known guest halts (a polling loop without its barrier?): '
                        + ', '.join(unknown[:20]))
    print(f'fused multiply-adds in recompiled functions: scalar {scalar_fma} (the guest\'s own), vector '
          f'{sum(vector_fma.values())} in {len(vector_fma)} functions '
          f'({sum(allowed_vector_fma.values())} allowed in the reference)')
    unexpected_vector_fma = vector_fma - allowed_vector_fma
    if unexpected_vector_fma:
        failures.append('unexpected vector fmla/fmls in recompiled code (contraction leaked?): '
                        + ', '.join(f'{name} x{count}' for name, count in unexpected_vector_fma.most_common(10)))
    if failures:
        print('\nFAILED:\n  - ' + '\n  - '.join(failures))
        sys.exit(1)
    print('\nall checks passed')


if __name__ == '__main__':
    main()
