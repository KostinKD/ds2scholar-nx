# HOME forwarder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans; execute inline.

**Goal:** Build and validate a DS2 SotFS NSP-forwarder for HOME, 39-bit and cores0–3.
**Architecture:** Pinned Forwarder-Mod loader and hacBrewPack; Python handles assets,
configuration and artifact validation, Windows wrapper supplies the local toolchain.
**Tech Stack:** Python3, devkitA64/libnx, MSYS2 make/MinGW, npdmtool/elf2nso.
**Spec:** ../specs/2026-11-05-home-forwarder-design.md

## Global Constraints

- Target: sdmc:/switch/ds2scholar-nx/ds2.nro; Title ID01445332534F0000.
- NPDM39-bit, ACI0/ACID cores0–3. NACP StartupUserAccount=1.
- No change to game/runtime/renderer, saves or global hbloader.
- Secret keys remain local; no key values or raw packer output in logs.
- Builds/checks via tools/win/run.ps1; generated outputs ignored.

## Review Focus

- NRO ASET bounds/signatures and missing icon/NACP must fail before packaging.
- Check both NPDM permission tables; verify actual encoded cores, address space and ID.
- Preserve NRO identity/version while requesting user selection.
- Reject unsafe paths/IDs and existing output overwrites.
- Error handling must not expose key values or copy keys into deliverables.

## Task1: Artifact preparation and verification

Files: tools/forwarder.py; tools/tests/test_forwarder.py.
- [x] Write failing unit tests for valid/malformed NRO assets, loader policy,
  bad NPDM flags/second core table/Title ID, and NACP user selection.
- [x] Observe RED, implement minimum helpers/CLI, verify GREEN.

## Task2: Real native build

Files: tools/win/build_forwarder.ps1; tools/forwarder.py; docs/forwarder.md.
- [x] Fetch exact source commits into ignored output and verify SHA/revisions.
- [x] Build loader with local devkitA64 and packer with native toolchain.
- [x] Package with local prod.keys, validate actual NPDM/NACP and NSP contents.
- [x] Generate license/instructions/checksums; upload NSP using switch_upload --backup.

## Task3: Verification and handoff

- [x] Run tests, build validation and review branch once with fresh reviewer.
- [x] Record done/unverified/next in progress, commit only this branch's changes.
- [ ] Console: installation, HOME boot, user identity, core mask0xf, HOME/exit/sleep.

## Ledger

Baseline: isolated worktree out/worktrees/forwarder at fbb2336d; existing main
workspace modifications untouched. User explicitly selected the previously
documented forwarder approach; continue without another permission loop.

Ruling: preserve the no-space SDK junction rather than resolving it, since
GNU make splits the actual Program Files path; regression RED→GREEN.
Review: untracked dependency inputs could enter Makefile wildcard builds;
replaced directory copies with git archive of the pinned commit, RED→GREEN.
Custom Title ID verifier corrected, RED→GREEN. Final suite15/15; reviewed
native build exit0; FTP read-back SHA matches. Verification does not decrypt
NCA internals; console launch and real mask0xf remain pending owner action.
