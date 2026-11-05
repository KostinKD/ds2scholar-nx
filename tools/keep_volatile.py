#!/usr/bin/env python3
"""Guest loads/stores stay volatile inside chosen functions (post-codegen step after tools/pch_no_volatile.py).

ds2-nx, stage 5 (2026-10-18, docs/progress.md entries 42-44): on the console GCC 16.1.0 (devkitA64) turns
sub_82997E24 - the XDK's vector memcpy for an unaligned source - into code that copies wrong data once its code moves:
with loop barriers (bisection, 16 rounds) and also without them once guest memory is not volatile (step 2 NRO 791c501f,
48 unidentified pixel shaders). This wraps each listed function in
    #pragma push_macro / #define REX_GUEST_VOLATILE volatile ... #pragma pop_macro
so its REX_LOAD_*/REX_STORE_* keep the generated (volatile) form while the rest of the file keeps whatever
REX_GUEST_VOLATILE was (none, or -DREX_GUEST_VOLATILE=volatile with DS2_GUEST_VOLATILE). Idempotent.

  python tools/keep_volatile.py app/generated/default [--check]
"""
import os
import re
import sys

KEEP_VOLATILE = {'sub_829C7FF4'}  # SotFS; ds2-nx sub_82997E24 (byte-identical, same FNV hash)
BEGIN = ('#pragma push_macro("REX_GUEST_VOLATILE")  // tools/keep_volatile.py\n#undef REX_GUEST_VOLATILE\n'
         '#define REX_GUEST_VOLATILE volatile')
END = '#pragma pop_macro("REX_GUEST_VOLATILE")  // tools/keep_volatile.py (end)'
FUNC = re.compile(r'^DEFINE_REX_FUNC\((sub_[0-9A-F]{8})\)')


def process(folder, check):
    found, files = set(), 0
    for f in sorted(os.listdir(folder)):
        if not re.match(r'\w+_recomp\.\d+\.cpp$', f):
            continue
        path = os.path.join(folder, f)
        text = open(path, encoding='utf-8', newline='').read()
        if not any(f'DEFINE_REX_FUNC({name})' in text for name in KEEP_VOLATILE):
            continue
        # Without the wrappers of an earlier run: they are placed again.
        text = text.replace(BEGIN + '\n', '').replace(END + '\n', '')
        lines, out, i = text.split('\n'), [], 0
        while i < len(lines):
            m = FUNC.match(lines[i])
            if not (m and m.group(1) in KEEP_VOLATILE):
                out.append(lines[i])
                i += 1
                continue
            found.add(m.group(1))
            j = i
            while j < len(lines) and lines[j] != '}':
                j += 1
            out += BEGIN.split('\n') + lines[i:j + 1] + END.split('\n')
            i = j + 1
        new = '\n'.join(out)
        if new != open(path, encoding='utf-8', newline='').read():
            files += 1
            if not check:
                open(path, 'w', encoding='utf-8', newline='\n').write(new)
    missing = KEEP_VOLATILE - found
    if missing:
        sys.exit(f'keep_volatile: not found in {folder}: {sorted(missing)}')
    print(f'{folder}: {len(found)} functions kept volatile, {files} files changed')
    return not (check and files)


def main():
    check = '--check' in sys.argv
    folders = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not folders:
        sys.exit(__doc__)
    sys.exit(0 if all([process(f, check) for f in folders]) else 1)


if __name__ == '__main__':
    main()
