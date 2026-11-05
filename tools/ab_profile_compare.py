#!/usr/bin/env python3
"""Compares console rex_profile.log files of a CPU A/B test (docs/switch-cpu-ab.md).

The variant of each log is the file name up to the first '_' (baseline_measure_1.log -> baseline), or
--variant NAME=GLOB. For every log it takes the 10-second reports after --skip-s and prints the game fps
(median / mean / min), CPU total, the CPU of the main game thread and of "GPU ring native", and checks that the
clocks stayed the same. With --elf NAME=PATH it also tells which build wrote the log: the size between "image" and
"code up to" in the first line must equal the end of the executable segment of that ELF, rounded to a page.

  python -I tools/ab_profile_compare.py logs/ab/*.log --skip-s 60 --elf baseline=out/nx/keep/codex_omitfp_baseline/ds2.elf --elf omitfp=out/nx/keep/ds2_omitfp.elf

The 10-second report is an average: it gives no frame-time distribution (p95/p99), see docs/switch-cpu-ab.md.
"""
import argparse
import collections
import fnmatch
import os
import re
import statistics
import struct

HEAD_RE = re.compile(r'^image 0x([0-9a-f]+), code up to 0x([0-9a-f]+)')
REPORT_RE = re.compile(r'^==== ([\d.]+) s \| mode: (\S+) \| game ([\d.]+) fps \| CPU total (\d+)%')
CLOCKS_RE = re.compile(r'^\s+clocks: CPU ([\d.]+) MHz, GPU ([\d.]+) MHz, memory ([\d.]+) MHz')
THREAD_RE = re.compile(r'^-- thread \d+ "([^"]*)": CPU ([\d.]+)%')
# switch_profile_waits = true: "   waits: blocked B% (sleep a, condvar b, mutex c, handles d, address e) | neither ... R%"
WAITS_RE = re.compile(r'^\s+waits: blocked [\d.]+% \(sleep ([\d.]+), condvar ([\d.]+), mutex ([\d.]+), '
                      r'handles ([\d.]+), address ([\d.]+)\) \| neither running nor blocked ([\d.]+)%')
WAIT_KINDS = ('sleep', 'condvar', 'mutex', 'handles', 'address', 'ready')


def elf_code_size(path):
    """End of the executable PT_LOAD segment, page-rounded (the NRO maps the image from vaddr 0)."""
    with open(path, 'rb') as f:
        data = f.read(64)
        if data[:4] != b'\x7fELF' or data[4] != 2:
            raise ValueError(f'{path}: not an ELF64')
        phoff, = struct.unpack_from('<Q', data, 0x20)
        phentsize, phnum = struct.unpack_from('<HH', data, 0x36)
        f.seek(phoff)
        ph = f.read(phentsize * phnum)
    end = 0
    for i in range(phnum):
        p_type, p_flags, _off, vaddr, _pa, _fsz, memsz = struct.unpack_from('<IIQQQQQ', ph, i * phentsize)
        if p_type == 1 and p_flags & 1:
            end = max(end, vaddr + memsz)
    return (end + 0xFFF) & ~0xFFF


def parse(path):
    run = {'code': None, 'reports': []}
    cur = None
    thread = None
    elapsed = 0.0  # the "==== N s" header is the length of the interval, not the time since start
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            if run['code'] is None:
                m = HEAD_RE.match(line)
                if m:
                    run['code'] = int(m.group(2), 16) - int(m.group(1), 16)
                    continue
            m = REPORT_RE.match(line)
            if m:
                elapsed += float(m.group(1))
                cur = {'t': elapsed, 'mode': m.group(2), 'fps': float(m.group(3)),
                       'cpu': int(m.group(4)), 'clocks': None, 'main': None, 'ring': None, 'waits': {}}
                thread = None
                run['reports'].append(cur)
                continue
            if cur is None:
                continue
            m = CLOCKS_RE.match(line)
            if m:
                cur['clocks'] = tuple(float(x) for x in m.groups())
                continue
            m = WAITS_RE.match(line)
            if m and thread:
                # Several threads share a name (MtTaskWorkerThr): their shares add up.
                prev = cur['waits'].get(thread)
                vals = [float(x) for x in m.groups()]
                cur['waits'][thread] = [a + b for a, b in zip(prev, vals)] if prev else vals
                continue
            m = THREAD_RE.match(line)
            if m:
                name, cpu = m.group(1), float(m.group(2))
                thread = name
                cur.setdefault('tcpu', collections.Counter())[name] += cpu
                if name.startswith('Main XThread'):
                    cur['main'] = cpu
                elif name.startswith('GPU ring native'):
                    cur['ring'] = cpu
    return run


def print_waits(reps, top):
    """switch_profile_waits: per thread, ms per frame running / blocked by svc / ready without a core (mean over
    the kept reports; a report's % of 10 s times its frame time)."""
    reps = [r for r in reps if r['waits'] and r['fps'] > 0]
    if not reps:
        return
    cpu = collections.Counter()
    for r in reps:
        cpu.update(r.get('tcpu', {}))
    names = [n for n, _ in cpu.most_common() if all(n in r['waits'] for r in reps)][:top]
    frame = statistics.fmean(1000.0 / r['fps'] for r in reps)
    print(f'    ms per frame (mean frame {frame:.1f} ms; several threads with one name are added up):')
    print(f'    {"thread":18} {"run":>5} ' + ' '.join(f'{k:>7}' for k in WAIT_KINDS))
    for n in names:
        run = statistics.fmean(r['tcpu'][n] / 100.0 * 1000.0 / r['fps'] for r in reps)
        cols = [statistics.fmean(r['waits'][n][i] / 100.0 * 1000.0 / r['fps'] for r in reps)
                for i in range(len(WAIT_KINDS))]
        print(f'    {n[:18]:18} {run:5.1f} ' + ' '.join(f'{c:7.1f}' for c in cols))


def fmt(values, digits=1):
    values = [v for v in values if v is not None]
    if not values:
        return '-'
    return f'{statistics.median(values):.{digits}f}/{statistics.fmean(values):.{digits}f}'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('logs', nargs='+')
    ap.add_argument('--skip-s', type=float, default=60.0,
                    help='ignore reports ending before this time since start (menu, loading, warm-up)')
    ap.add_argument('--until-s', type=float, default=None, help='ignore reports ending after this time')
    ap.add_argument('--min-cpu', type=int, default=0,
                    help='ignore reports with CPU total below this (menu is ~70%%, the world 250%%+)')
    ap.add_argument('--variant', action='append', default=[], metavar='NAME=GLOB',
                    help='variant of the logs whose file name matches GLOB (default: name up to the first "_")')
    ap.add_argument('--elf', action='append', default=[], metavar='NAME=PATH', help='identify the build by its ELF')
    ap.add_argument('--wait-threads', type=int, default=10,
                    help='with switch_profile_waits: how many threads (by CPU) get the ms-per-frame breakdown')
    args = ap.parse_args()

    elves = {}
    for spec in args.elf:
        name, path = spec.split('=', 1)
        size = elf_code_size(path)
        elves[size] = f'{elves[size]}+{name}' if size in elves else name
    globs = [spec.split('=', 1) for spec in args.variant]

    pooled = collections.defaultdict(list)
    print(f'reports {args.skip_s:g} s .. {args.until_s if args.until_s is not None else "end"}, mode normal, '
          f'CPU total >= {args.min_cpu}%; '
          'columns are median/mean')
    print(f'{"log":34} {"variant":10} {"build":10} {"n":>3} {"fps":>11} {"min":>5} {"CPU%":>11} '
          f'{"main%":>11} {"ring%":>11}  clocks CPU/GPU/mem')
    for path in args.logs:
        base = os.path.basename(path)
        variant = next((n for n, g in globs if fnmatch.fnmatch(base, g)), base.split('_', 1)[0])
        run = parse(path)
        reps = [r for r in run['reports'] if r['mode'] == 'normal' and r['t'] >= args.skip_s
                and r['cpu'] >= args.min_cpu and (args.until_s is None or r['t'] <= args.until_s)]
        build = elves.get(run['code'], '?') if elves else '-'
        clocks = sorted({r['clocks'] for r in reps if r['clocks']})
        clock_txt = ' | '.join('/'.join(f'{c:g}' for c in cl) for cl in clocks) or '-'
        if len(clocks) > 1:
            clock_txt += '  <- clocks changed'
        fps = [r['fps'] for r in reps]
        print(f'{base[:34]:34} {variant[:10]:10} {build[:10]:10} {len(reps):3} {fmt(fps):>11} '
              f'{(min(fps) if fps else 0):5.1f} {fmt([r["cpu"] for r in reps]):>11} '
              f'{fmt([r["main"] for r in reps]):>11} {fmt([r["ring"] for r in reps]):>11}  {clock_txt}')
        if elves and build != '?' and variant not in build.split('+'):
            print(f'    warning: file name says {variant}, code size 0x{run["code"]:x} says {build}')
        if elves and build == '?':
            print(f'    warning: code size 0x{run["code"]:x} matches none of the given ELFs')
        pooled[variant].append(fps)
        print_waits(reps, args.wait_threads)

    print('\nper variant (each run weighs the same: median of the run medians; all reports pooled)')
    for variant, runs in pooled.items():
        meds = [statistics.median(r) for r in runs if r]
        allv = [v for r in runs for v in r]
        if not meds:
            print(f'  {variant}: no reports')
            continue
        spread = f'{min(meds):.1f}..{max(meds):.1f}'
        print(f'  {variant:10} runs {len(meds)} | run medians {spread} -> {statistics.median(meds):.1f} | '
              f'pooled median {statistics.median(allv):.1f}, mean {statistics.fmean(allv):.1f}, n {len(allv)}')


if __name__ == '__main__':
    main()
