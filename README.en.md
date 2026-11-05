# Dark Souls II: Scholar of the First Sin — Nintendo Switch

<p align="center">
  <img src="docs/images/ds2-scholar-banner.jpg" alt="Dark Souls II: Scholar of the First Sin" width="480">
</p>

Русский · [Full player guide](docs/players/README.md#english) · [FPS settings](#maximum-fps)

Unofficial port of **Xbox 360 SotFS** for Switch, with HOME launch, saves,
controller support and online play through the project server.
**Experimental release:** a full playthrough and all DLC areas remain unverified.

## Quick start

You need **Atmosphère, hbmenu and DBI**, about **8 GB** free on SD,
your own Xbox 360 SotFS **GoD + Compatibility Pack 4**, and a PC with Python 3.10+.

1. Extract the player package and copy its `switch` folder to the SD root.
2. Extract your game and Compatibility Pack 4 using the [steps below](#install).
3. Install `ds2scholar-forwarder.nsp` with **DBI**, start **DS2 from HOME**,
   and choose your usual Switch user.

Keep the NRO and game folder on SD. Preserve `game_root/` and `ds2/` when updating.
Game data is not included; the source ZIP alone is not ready to play.

| Goal | Settings |
|---|---|
| Steadier 30 FPS | Supplied config: 30 FPS cap, dynamic 720p/540p, FSR 1 |
| Maximum FPS | **FSR 1 + fixed 540p + cap disabled** — [setup](#maximum-fps) |

Main tests: handheld OLED, CPU 1785 / GPU 921.6 / RAM 2133 MHz.
Heavy scenes can drop frames; stock-clock results will differ.

## Requirements

- Switch with Atmosphère, hbmenu and DBI; about **8 GB** free on SD.
- Your own Xbox 360 Games on Demand copy and **Compatibility Pack 4**.
  The pack is required to start the game. PC, PS3 and later console versions
  cannot be used as input for this port.
- PC with **Python 3.10+** for extraction.

The prepared package contains NRO `1.10.0-access1`, `ds2.toml`,
`sa2_shaders.mesp`, `sa2_shaders.mesp.idx` and `ds2scholar-forwarder.nsp`
in `switch/ds2scholar-nx/`, with `extract-tools` and licenses at the ZIP root.
Game files, keys and saves are not included. A source checkout is not a ready-to-play package.

## Install

1. Copy the package's `switch` folder to the SD root.
2. From the extracted package directory, unpack your game (about 6 GB):

   ```powershell
   python extract-tools/god_extract.py "<your files>\465307E4\00007000\<game file>" -o "<SD>\switch\ds2scholar-nx\game_root"
   ```

   Keep `<game file>.data` beside the GoD header during extraction.
3. Unpack your Compatibility Pack 4 (about 1.2 GB):

   ```powershell
   python extract-tools/stfs_extract.py "<your files>\465307E4\00000002\D4B91B6B4DA1509C280F56F77B09203DE7D39AE646" "<SD>\switch\ds2scholar-nx\ds2\0000000000000000\465307E4\00000002\D4B91B6B4DA1509C280F56F77B09203DE7D39AE646"
   ```

4. Install `switch/ds2scholar-nx/ds2scholar-forwarder.nsp` with **DBI**.
5. Start the **DS2** tile from HOME. Choose the **same Switch user** as before:
   saves and online identity depend on that user.

Keep `sdmc:/switch/ds2scholar-nx/ds2.nro` and the entire game folder on SD:
the NSP launches that NRO. HOME launch, saves and the selected cover have been
confirmed on the owner's console. If an old icon remains after reinstalling
the NSP, fully restart the console/Atmosphère. Copying the NSP to SD alone
does not update an installed tile.

The forwarder requests a 39-bit address space and cores **0–3**. The console log
confirmed process mask `0xF`; a speedup from the fourth core has not been measured.
Alternative: hold **R** while starting an installed game to open hbmenu
(title override), then start the port. Fourth-core access depends on the loader.
Album applet mode does not provide enough memory.

## Updates and controls

Keep `game_root/` and **`ds2/`**, which contains saves and the compatibility pack.
Back up your existing `ds2.toml`, compare it with the new supplied config and
carry over the settings you need. Install an updated NSP over the existing one
through DBI. Continue choosing the same Switch user.

Buttons follow **Switch letters**: A confirms, B cancels/rolls
(`input_xbox_layout = false`). Other settings are in `ds2.toml`.

## Maximum FPS

For the highest frame rate, start the supplied PGO+LTO build from the **DS2 HOME
tile** and use the recommended maximum-FPS profile: **FSR 1 + fixed 540p +
the 30 fps cap disabled** in handheld mode.
This trades image sharpness and even frame pacing for higher frame rates.

| Shortcut | Action |
|---|---|
| L + R + Minus | Toggle the 30 fps cap |
| L + R + Plus | Toggle dynamic resolution |
| L + R + right-stick click | Cycle dynamic / fixed 720p / fixed 540p |
| L + R + left-stick click | Cycle the upscaler — select FSR 1 |

1. Back up `sdmc:/switch/ds2scholar-nx/ds2.toml` and close the game.
2. Edit the existing keys below, adding the render-height key if absent. Keep
   the remaining supplied optimizations enabled; avoid duplicate TOML keys.

   ```toml
   present_effect = "fsr"
   ds2_frame_cap_30 = false
   ds2_dynamic_resolution = false
   sa2_render_height_handheld = 540
   ds2_vpos_render_scale = true
   ```

3. Start the game again. Check the on-screen notification for the selected mode.
   The config above selects FSR 1 and 540p on the next launch.

For a steadier **30 fps** presentation, keep the supplied settings instead:
`ds2_frame_cap_30 = true`, `ds2_dynamic_resolution = true`, and the default
handheld render height of 720. Dynamic resolution can then drop to 540p under load.
If you added the fixed-540p line, remove it or change it to 720 before using this preset.

**Clock conditions matter.** The main tests used a handheld **Switch OLED** at
**CPU 1785 / GPU 921.6 / RAM 2133 MHz**, configured externally. The port does
not install an overclocking setup or automatically apply these three frequencies.
If you already use a compatible clock manager, apply the profile to the forwarder
title **`01445332534F0000`** and check the actual clocks after opening HOME.
These are measured conditions for that console, not a universal maximum or a
validated profile for every Switch model. Use frequencies supported by your setup.

Historical uncapped measurements at those clocks in a static Majula bonfire scene
were about **33 fps at 720p** and **40 fps at 540p**; a CPU-bound Heide's Tower
test was about **32 fps**. These were earlier optimization builds, not a new
benchmark of `1.10.0-access1`. Lower resolution helps GPU-bound scenes; it does
not remove CPU or streaming stalls. Stable 60 fps has not been demonstrated.
The forwarder exposes cores 0–3, but its FPS gain has not been measured.

Keep the bundled FSR/FXAA settings as the tested image-quality baseline.
Their individual FPS cost has not been established, so disabling them is not
presented as a measured improvement. The separate PGO ZIP is for developers;
the player NRO already contains the build optimizations.

## Online

The supplied config uses **`ds2scholar.download`** with server relay enabled;
no router port forwarding is needed. Availability depends on the project server.
Messages, ratings, bloodstains, ghosts, summon signs and player names have been
tested. Switch/PC summons and invasions passed tests on 29 October 2026;
after the reconnect fix, world entry in both directions was confirmed again
on **1 November**.

Your online identity follows your Switch user. Your nickname is transliterated
from Cyrillic; unsupported names fall back to `Player-XXXX`. Override it with
`net_profile_name = "YourName"` in `ds2.toml`: Latin letters, digits, spaces and
`_ - .`, up to 15 characters. When migrating to user-based identity, older saves
are copied once; the original folder remains.

The console-key server gate (`access1`) has not completed end-to-end validation;
the NRO version label alone does not confirm that feature.

## Limits and help

- Target: 30 fps, dynamic 720p/540p, FSR 1 and FXAA. Main measurements used
  handheld Switch OLED at CPU 1785 / GPU 921.6 / RAM 2133 MHz. Heavy scenes and
  loading can drop frames; stock-clock performance is not promised. TV mode has less coverage.
- A full playthrough, all DLC areas, 3–4-player co-op and network recovery after
  sleep have not been fully tested.
- A PC null-address crash after returning from a summon remains unresolved;
  the same crash has not been confirmed on Switch.
- If repeated multiplayer disconnects trigger a Bone of Order warning, use that
  item on the affected character. Server settings do not remove this game restriction.
- Lighting flicker/a black square was observed in a corner of McDuff's workshop.

Logs: `sdmc:/switch/ds2scholar-nx/logs/ds2_NNN.log` (largest number is newest).
Include the latest log, version, location, steps and handheld/TV mode in a bug report.

The separate **PGO ZIP is optional and only needed for rebuilding**, not playing:
[PGO instructions](docs/pgo-profile.md), [rebuild instructions](docs/rebuild.md).
When extracting from a source checkout, use `tools/` instead of `extract-tools/`.

## Development

Use a full Git clone with history for PGO installation and release packaging.
The source ZIP is a file snapshot. See [rebuild instructions](docs/rebuild.md),
[workflow](docs/workflow.md), [clean-build report](docs/clean-build.md),
[forwarder details](docs/forwarder.md) and [third-party notices](THIRD_PARTY_NOTICES.md).
