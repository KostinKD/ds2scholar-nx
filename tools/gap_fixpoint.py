#!/usr/bin/env python3
"""Repeat the structural gap scan until no newly exposed gap qualifies.

Each pass: find_gaps.py on the current generated code -> gaps of 8..1024 bytes not examined before -> scratch
codegen with them declared -> gap_classify.py checks (tier 1 + no stack/LR + no undefined-at-entry registers, and
tier 2) -> append the accepted entries to app/overrides.toml -> real codegen (tools/codegen.sh), so the next pass
sees the code the new entries exposed. Evidence goes to <scratch>/gapscan-accepted.txt. Stops when a pass accepts
nothing.

  python3 tools/gap_fixpoint.py SCRATCH_DIR [examined.txt ...]

SCRATCH_DIR  work folder (one subfolder per pass; it is not cleaned).
examined.txt files whose lines start with an address that must not be examined again (selected.txt of earlier
             runs).

Environment: REXGLUE = path of the rexglue host tool (default sdk/out/host/rexglue, see tools/build_host.sh).
Needs the game in assets/game_root and an existing generated tree (tools/codegen.sh).
"""
import os, re, subprocess, sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = os.path.join(root, "app")
if len(sys.argv) < 2:
    sys.exit(__doc__)
scratch = os.path.abspath(sys.argv[1])
rexglue = os.path.abspath(os.environ.get("REXGLUE", os.path.join(root, "sdk", "out", "host", "rexglue")))
overrides_path = os.path.join(app, "overrides.toml")
manifest_path = os.path.join(app, "ds2_manifest.toml")
gen = os.path.join(app, "generated", "default")
evidence_path = os.path.join(scratch, "gapscan-accepted.txt")
tools = os.path.join(root, "tools")

sys.path.insert(0, tools)
import ppc_mini  # noqa: E402
image = ppc_mini.Image(os.path.join(root, "out", "default_image.bin"), 0x82000000)  # REXGLUE_DUMP_IMAGE of codegen
# The .pdata records of Default.xex, located through the PE section table of the dumped image (DS2 had them fixed at
# 0x821CA800/0x69ED0; SotFS: 0x821CE400/0x6B590, docs/analysis/xex.md). An address strictly inside a function with a
# record is not a function start (ds2-nx 2026-10-16: 13 gap-scan entries there cut their parents, mostly at a tail
# branch into a shared register-restore epilogue).
import bisect  # noqa: E402
import struct  # noqa: E402


def _pdata_section(data):
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    count = struct.unpack_from("<H", data, pe + 6)[0]
    table = pe + 24 + struct.unpack_from("<H", data, pe + 20)[0]
    for i in range(count):
        name, vsize, va = struct.unpack_from("<8sII", data, table + 40 * i)
        if name.rstrip(b"\0") == b".pdata":
            return 0x82000000 + va, vsize
    sys.exit("gap_fixpoint: no .pdata section in the image")


_pva, _psize = _pdata_section(image.data)
_pdata = sorted((image.word(_pva + 8 * k), image.word(_pva + 8 * k)
                 + ((image.word(_pva + 4 + 8 * k) >> 8) & 0x3FFFFF) * 4) for k in range(_psize // 8)
                if image.word(_pva + 8 * k))
_pdata_starts = [p[0] for p in _pdata]


def inside_pdata(addr):
    j = bisect.bisect_right(_pdata_starts, addr) - 1
    return j >= 0 and _pdata[j][0] < addr < _pdata[j][1]
ns = {"__name__": "gc"}
exec(compile(open(os.path.join(tools, "gap_classify.py")).read(), "gc", "exec"), ns)
examined = set()
for p in sys.argv[2:]:
    examined |= {l.split()[0] for l in open(p)}
os.makedirs(scratch, exist_ok=True)

for n in range(1, 20):
    d = os.path.join(scratch, f"pass{n}")
    os.makedirs(d, exist_ok=True)
    subprocess.run([sys.executable, os.path.join(tools, "find_gaps.py"), "--gen", gen,
                    "--report", f"{d}/h.txt", "--toml", f"{d}/c.toml"], capture_output=True)
    gaps = [(m.group(1), int(m.group(2))) for l in open(f"{d}/c.toml")
            for m in [re.match(r'"(0x[0-9A-F]+)" = \{ \}\s*#\s*(\d+) bytes', l)]
            if m and 8 <= int(m.group(2)) <= 1024]
    # ds2: a gap often holds a run of small functions (`li r3,7 ; blr`, the bodies of many short virtuals one after
    # the other). find_gaps declares only the first; one per pass took ~25 per 10-minute pass (2026-10-16, passes
    # 2-4). Also declare every start that follows a terminator (blr, bctr, an unconditional b) and its zero padding
    # inside the gap: each one still goes through the same scratch codegen and gap_classify checks.
    sel = []
    for a, s in gaps:
        start, end = int(a, 16), int(a, 16) + s
        cuts, p = [start], start
        while p < end:
            ins = ppc_mini.decode(image.word(p), p)
            p += 4
            if (ins.op == "b" and not ins.link) or (ins.op in ("bclr", "bcctr") and ins.unconditional):
                while p < end and image.word(p) == 0:
                    p += 4
                if p < end:
                    cuts.append(p)
        for c, nxt in zip(cuts, cuts[1:] + [end]):
            if f"0x{c:08X}" not in examined and nxt - c >= 4:
                sel.append((f"0x{c:08X}", nxt - c))
    examined |= {a for a, _ in sel}
    if not sel:
        print(f"pass {n}: no new gaps; fixpoint")
        break
    ov = open(overrides_path).read()
    m = re.search(r"^\[functions\]\s*$", ov, re.M)
    scratch_overrides = f"{d}/overrides.toml"
    open(scratch_overrides, "w").write(ov[:m.end()] + "\n" + "".join(f'"{a}" = {{ }}\n' for a, _ in sel) + ov[m.end():])
    open(f"{d}/selected.txt", "w").write("".join(f"{a} {s}\n" for a, s in sel))
    # Scratch manifest: same game, output in the pass folder, and the scratch overrides instead of the real ones.
    man = open(manifest_path).read()
    # Windows paths in TOML basic strings: a backslash starts an escape, so use forward slashes. ds2 has no
    # perf_overrides.toml: the scratch codegen takes the codegen flavour file, as the real one does.
    fs = lambda x: x.replace(os.sep, "/")
    root_, d_, app_, so_ = fs(root), fs(d), fs(app), fs(scratch_overrides)
    man = re.sub(r'^game_root = .*$', f'game_root = "{root_}/assets/game_root"', man, flags=re.M)
    man = re.sub(r'^file_path = .*$', f'file_path = "{root_}/assets/game_root/default.xex"', man, flags=re.M)
    man = re.sub(r'^out_directory_path = .*$', f'out_directory_path = "{d_}/generated"', man, flags=re.M)
    man = re.sub(r'^includes = .*$', f'includes = ["{so_}", "{app_}/switch_tables.toml", "{app_}/codegen_flavor.toml"]', man,
                 flags=re.M)
    open(f"{d}/manifest.toml", "w").write(man)
    r = subprocess.run([rexglue, "codegen", "manifest.toml"], cwd=d, capture_output=True, text=True)
    open(f"{d}/codegen.log", "w").write(r.stdout + r.stderr)
    if r.returncode:
        print(f"pass {n}: scratch codegen failed (see {d}/codegen.log)")
        break
    subprocess.run([sys.executable, os.path.join(tools, "gap_classify.py"), f"{d}/generated", f"{d}/selected.txt",
                    f"{d}/codegen.log", f"{d}/acc.txt"], capture_output=True)
    subprocess.run([sys.executable, os.path.join(tools, "gap_classify.py"), "--tier2", f"{d}/generated",
                    f"{d}/selected.txt", f"{d}/codegen.log", overrides_path, f"{d}/t2.txt"], capture_output=True)
    have = set(re.findall(r'"(0x[0-9A-Fa-f]+)"\s*=', ov))
    # ds2 (2026-10-16): gap_classify accepted case bodies and blocks after an early blr that read the parent's live
    # r29/r31; declared, they cut the parent, and its branches into them became "Unresolved" (REX_FATAL). Reject a
    # candidate that lies between the source and the target of an unresolved branch of the scratch codegen, or just
    # before the source of a forward one (it started the function that ends short of the target).
    slog = open(f"{d}/codegen.log", encoding="utf-8", errors="replace").read()
    unres = [(int(s_, 16), int(t_, 16)) for t_, s_ in re.findall(
        r"Unresolved (?:conditional branch to|b target) 0x([0-9A-F]+) from 0x([0-9A-F]+)", slog)]
    unres += [(int(s_, 16), int(t_, 16)) for t_, s_ in re.findall(
        r"Jump target 0x([0-9A-F]+) unresolved at bctr 0x([0-9A-F]+)", slog)]
    def splits_a_parent(addr):
        return any(min(s_, t_) < addr <= max(s_, t_) or (t_ > s_ and s_ - 0x200 <= addr <= s_) for s_, t_ in unres)
    accepted = []
    for l in open(f"{d}/acc.txt").readlines() + open(f"{d}/t2.txt").readlines():
        a, s, rest = l.split(" ", 2)
        ins = [i.strip() for i in rest.lstrip("| ").strip().split(" ; ")]
        ops = [i.split()[0] for i in ins]
        if (a in have or splits_a_parent(int(a, 16)) or inside_pdata(int(a, 16)) or any(re.search(r"\br1\b", i) for i in ins)
                or any(o in ("mtlr", "mflr", "ld", "std", "stwu", "lfd", "stfd") for o in ops)
                or ns["reads_undefined_at_entry"](ins)):
            continue
        accepted.append(l)
        have.add(a)
    print(f"pass {n}: {len(sel)} new gaps, {len(accepted)} accepted")
    if not accepted:
        print("fixpoint")
        break
    with open(evidence_path, "a") as ev_file:
        ev_file.writelines(accepted)
    block = (f"\n# Structural gap scan, fixpoint pass {n} of {os.path.basename(scratch)} (tools/gap_fixpoint.py; "
             f"evidence {os.path.basename(scratch)}/gapscan-accepted.txt).\n") + "".join(
        f'"{l.split()[0]}" = {{ }}  # {l.split()[1]} bytes, unclaimed gap: '
        f'{l.split(" ", 2)[2].lstrip("| ").strip()[:80]}\n' for l in accepted)
    open(overrides_path, "w").write(ov[:m.end()] + block + ov[m.end():])
    if os.name == "nt":  # ds2 on Windows: tools/codegen.ps1 (this repository has no codegen.sh)
        b = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                            os.path.join(tools, "codegen.ps1"), "-Rexglue", rexglue], capture_output=True, text=True)
    else:
        b = subprocess.run(["bash", os.path.join(tools, "codegen.sh")], capture_output=True, text=True,
                           env={**os.environ, "REXGLUE": rexglue})
    if b.returncode:
        print("codegen failed")
        print((b.stdout + b.stderr)[-2000:])
        break
    real_log = open(os.path.join(root, "out", "codegen.log"), encoding="utf-8", errors="replace").read()
    n_unres = len(re.findall(r"(?i)unresolved", real_log))
    if n_unres:  # the safety net: never go on with a tree that has REX_FATAL branches in it
        print(f"pass {n}: the real codegen logged {n_unres} 'Unresolved' lines (out/codegen.log); stopping")
        break
