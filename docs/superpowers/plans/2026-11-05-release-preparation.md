# Release preparation

Goal: one player ZIP with verified NRO, shaders, public config and owner-selected
HOME forwarder; updated RU/EN instructions and release assets. Use this isolated
release branch and preserve the original workspace. GitHub publication is separate.

- [x] Carry the completed rebuild tool/docs into this release branch.
- [x] Update README and bilingual guide for HOME/DBI, users, saves and cover refresh.
- [x] TDD: reject mismatched NRO/forwarder, missing inputs and existing outputs;
  add licenses, public config and SHA256 manifests automatically.
- [x] TDD: PGO excludes exact packaging-only paths, rejects game/codegen changes.
- [x] Correct inherited Mass Effect extraction message; synthetic and real XEX checks.
- [x] Build real public HOME ZIP; keep the optional PGO ZIP separate.
- [x] Review release branch, verify clean ZIP extraction/hashes and source audit.
- [x] Record readiness/limits, commit branch, export exact source ZIP.
- [x] Assemble release notes, artifact SHA256SUMS and publication checklist locally.

Review ruling:PGO/release packaging require Git history/index;explicitly document
the source ZIP as a snapshot. Fixed player-ZIP links with SOURCE_BUILD.md and
license-path rewriting;regression RED→GREEN,6/6 bundle tests.

No game/runtime changes or full game rebuild. Keep access1 NRO and wiki-cover
forwarder byte-for-byte. Source ZIP excludes ignored game/generated/profile/key/
build data. Playing does not require the PGO ZIP.

Review focus: exact runtime/forwarder hashes; public config without LAN identity;
required shader/extraction files; preservation of saves/custom config; accurate
tested/unverified claims. Experimental release: full playthrough, all DLC,3–4 co-op,
sleep networking and fresh SD installation remain outside verified coverage.
