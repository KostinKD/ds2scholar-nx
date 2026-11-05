# Third-party notices and credits

ds2scholar-nx is a Nintendo Switch port of Dark Souls II: Scholar of the First Sin
using ReXGlue. It started from the local ds2-nx port, whose SDK, native renderer
and tools were carried over and adapted for SotFS starting on 2026-10-21.

The port's application code, tools and documentation are distributed under
GPL-3.0; see [LICENSE](LICENSE), copied verbatim from sa2-nx. Existing notices
and the licenses of individual components remain in effect. In particular,
the SDK retains its BSD-3-Clause license and XenosRecomp retains its MIT license.
The root license does not grant rights to the original game's code or assets.

## Projects and authors

The attribution below follows the notices in the neighboring sa2-nx and nfsmw-nx
ports and the source comments retained in this repository.

| Project / authors | Contribution | License / notice |
|---|---|---|
| ds2-nx; ds2scholar-nx by KostinKD and contributors | DS2 port used as the starting point; SotFS adaptation, renderer work, tooling and online support | GPL-3.0 for port code; component licenses below |
| sa2-nx by ChanseyIsTheBest and contributors | Renderer, SDK integration, tools and performance work inherited through ds2-nx | GPL-3.0; SDK BSD-3-Clause; shader translator MIT |
| [masseffect-nx](https://github.com/nebadasSwifty/masseffect-nx) by NebadasSwifty | Native renderer (`app/src/me`), application framework and tools inherited through the earlier ports | GPL-3.0; SDK BSD-3-Clause |
| banjo-nx contributors | Renderer platform compatibility adaptations identified in `app/src/me` comments | Retained source notices and inherited component licenses |
| [nfsmw-nx](https://github.com/StevensND/nfsmw-nx) by StevensND | Horizon layer, toolchain, profiling and PGO tooling inherited through the earlier ports | GPL-3.0; SDK portions BSD-3-Clause |
| [NFSMW Recompiled](https://github.com/madelrandel-blip/NFSMW-Recompiled) by madelrandel-blip | Application and build/tooling ancestry documented by the earlier ports | GPL-3.0 |
| [ReXGlue SDK](https://github.com/rexglue/rexglue-sdk) by Tom Clay; [Xenia](https://xenia.jp) by Ben Vanik and contributors | Code generator, Xbox 360 runtime, kernel services and GPU command processing | BSD-3-Clause; [sdk/LICENSE](sdk/LICENSE) |
| [XenosRecomp](https://github.com/hedge-dev/XenosRecomp) by hedge-dev and contributors | Xenos microcode to HLSL translator, with inherited port changes | MIT; [shaders/LICENSE.md](shaders/LICENSE.md) |
| [mesa-switch](https://github.com/danfromtico/mesa-switch) by danfromtico and contributors; [Mesa](https://mesa3d.org) contributors | External Vulkan/NVK driver and NAK compiler used by the Switch build | Mesa's per-file licenses; notices belong with the driver distribution |

## Libraries

Third-party source notices remain alongside the code in `sdk/thirdparty`.
This is an index of major components, not a replacement for their license files.
Some components are build tools or desktop/test dependencies rather than part of
the Switch executable.

| Component | License / local notice |
|---|---|
| FFmpeg (audio and WMV decoding) | LGPL-2.1-or-later for the non-GPL configuration; [license details](sdk/thirdparty/FFmpeg/LICENSE.md), [LGPL text](sdk/thirdparty/FFmpeg/COPYING.LGPLv2.1) |
| libmspack by Stuart Caie (LZX decompression) | LGPL-2.1; [COPYING.LIB](sdk/thirdparty/libmspack/libmspack/COPYING.LIB) |
| Monocypher 4.0.2 by Loup Vaillant and contributors (Ed25519 console keys) | BSD-2-Clause or CC0; [LICENCE.md](sdk/thirdparty/monocypher/LICENCE.md), [source/version note](sdk/thirdparty/monocypher/README.ds2scholar) |
| glslang | BSD and other notices; [LICENSE.txt](sdk/thirdparty/glslang/LICENSE.txt) |
| SPIRV-Tools | Apache-2.0; [LICENSE](sdk/thirdparty/spirv-tools/LICENSE) |
| SPIRV-Headers | MIT; [LICENSE](sdk/thirdparty/spirv-headers/LICENSE) |
| Vulkan-Headers, Vulkan loader, MoltenVK | Respective upstream license files in `sdk/thirdparty` |
| Vulkan Memory Allocator | MIT; [LICENSE.txt](sdk/thirdparty/vulkan-memory-allocator/LICENSE.txt) |
| fmt, spdlog, SIMDe, toml++, Dear ImGui, o1heap, inja, Tracy | MIT; respective upstream license files in `sdk/thirdparty` |
| xxHash | BSD-2-Clause; [LICENSE](sdk/thirdparty/xxHash/LICENSE) |
| utfcpp, Catch2 | BSL-1.0; respective upstream license files in `sdk/thirdparty` |
| CLI11 | BSD-3-Clause; [LICENSE](sdk/thirdparty/cli11/LICENSE) |
| AES-128 by LuoPeng, tiny-AES-c, DES and other crypto helpers | Respective notices in `sdk/thirdparty/aes_128`, `tiny-aes-c` and `crypto` |
| SDL3 | zlib license; upstream notices in `sdk/thirdparty/sdl3` |
| DirectXShaderCompiler and shader tooling | Upstream notices in `sdk/thirdparty/dxc`, `dxbc` and `shaders/` |
| disruptorplus, RenderDoc API, PowerPC disassembler, stb and PE helpers | Retained upstream notices in their `sdk/thirdparty` directories |
| libnx and devkitA64 runtime | ISC and respective newlib/GCC runtime licenses; external devkitPro dependencies |

## Local changes and rebuilding

Modified source is kept in this repository, including the SDK's Horizon backend,
renderer adaptations, shader tools, FFmpeg configuration and build overlays.
See [docs/workflow.md](docs/workflow.md) for the current build procedure and
docs/progress.md for dated changes and verification limits.
A Switch build from a clean clone was verified on 3 November 2026 on the
prepared Windows machine; see [docs/clean-build.md](docs/clean-build.md).
Rebuilding the external Mesa/NVK dependency and setup on a clean operating
system remain unverified.

Game data, generated game code, compiled game shaders and built executables are
excluded from Git. Obtain the game files separately from your own copy.

## Game and platform names

Dark Souls II: Scholar of the First Sin and its original content belong to their
respective rights holders, including FromSoftware and Bandai Namco. Nintendo
Switch and Xbox 360 names belong to their respective owners. This is an
independent community project and is not affiliated with or endorsed by them.
