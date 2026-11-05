#!/bin/bash
# Stage 5: builds the NVK driver (static libvulkan.a) for the Switch from mesa-switch with nfsmw-nx's patch, in MSYS2.
# The same driver sa2-nx links (sa2-nx/mesa/README.md -> nfsmw-nx/mesa/README.md, docs/mesa.md).
#
#   G:/msys64/usr/bin/bash.exe -l tools/switch/build_nvk_msys2.sh            (MSYSTEM=MINGW64)
#
# Expects (docs/progress.md, stage 5): MSYS2 at G:/msys64 (junction to "G:/Program Files/msys64"; MSYS2 and devkitPro
# cannot work from a path with a space) with the MINGW64 packages, devkitPro's switch-dev in /opt/devkitpro of that
# MSYS2, Rust (GNU toolchain, aarch64-unknown-linux-gnu target, bindgen, cbindgen) at G:/Rust (junction to
# "G:/Program Files/Rust"), and mesa-switch checked out at 1a8c1a66d6f with nfsmw-nx/mesa/mesa-switch-nfsmw.patch in
# $MESA (default G:/DS2Switch/mesa-switch).
#
# mesa-switch's build files name C:/msys64 and the clang64/clangarm64 environments; nfsmw-nx's docs/mesa.md (problems
# 1, 2, 3, 6, 7) says what to change for a MINGW64 build. This script makes those changes in the checkout (idempotent).
# Result: $MESA/mesa-unified-install/opt/devkitpro/portlibs/switch (NVK_SDK for tools/win/build_switch.ps1).
set -euo pipefail
MESA=${MESA:-/g/DS2Switch/mesa-switch}
MSYS_WIN=${MSYS_WIN:-G:/msys64}
RUST_WIN=${RUST_WIN:-G:/Rust}
cd "$MESA"

# Machine paths: C:/msys64 -> G:/msys64; host tools on CLANG64 (see below); cbindgen from rustup's cargo (problem 6).
for f in switch_cross_file_msys2.txt windows_x64_host_cross_file_msys2.txt switch_native_tools_msys2.txt \
         rustc-switch-wrapper.sh rustc-native-msys2-wrapper.sh bindgen-switch-wrapper.sh switch-pkg-config-wrapper.sh; do
  sed -i "s#C:/msys64#${MSYS_WIN}#g" "$f"
done
# The host tools (mesa_clc, vtn_bindgen2) stay on CLANG64 as upstream: on MINGW64 (msvcrt) vtn_private.h switches to
# __builtin_setjmp, which clang rejects for a jmp_buf (2026-10-17, spirv_to_nir.c:412). Undo an earlier mingw64 edit.
sed -i "s#${MSYS_WIN}/mingw64/#${MSYS_WIN}/clang64/#g" windows_x64_host_cross_file_msys2.txt
# And by their real path: llvm-config resolves the G:/msys64 junction to "G:/Program Files/msys64", so with clang
# called through the junction meson did not recognise LLVM's include folder as clang's own system folder and passed it
# with -I, which breaks libc++'s include_next (2026-10-17, clc_helpers.cpp: "<cstdlib> tried including <stdlib.h> but
# didn't find libc++'s <stdlib.h>").
MSYS_REAL=${MSYS_REAL:-G:/Program Files/msys64}
sed -i "s#${MSYS_WIN}/clang64/#${MSYS_REAL}/clang64/#g" windows_x64_host_cross_file_msys2.txt
sed -i "s#^cbindgen = .*#cbindgen = '${RUST_WIN}/cargo/bin/cbindgen.exe'#" switch_native_tools_msys2.txt
# Problem 7: devkitA64's own system headers for bindgen (the libnx ones are already there).
grep -q "aarch64-none-elf/include" switch_cross_file_msys2.txt || \
  sed -i "s#'-isystem', '${MSYS_WIN}/opt/devkitpro/libnx/include'#'-isystem', '${MSYS_WIN}/opt/devkitpro/libnx/include', '-isystem', '${MSYS_WIN}/opt/devkitpro/devkitA64/aarch64-none-elf/include'#" switch_cross_file_msys2.txt

export DEVKITPRO=${MSYS_WIN}/opt/devkitpro
export RUSTUP_HOME=${RUST_WIN}/rustup CARGO_HOME=${RUST_WIN}/cargo
export RUSTUP_TOOLCHAIN=stable-x86_64-pc-windows-gnu
export MESA_SWITCH_RUSTC=/g/Rust/cargo/bin/rustc.exe
export LIBCLANG_PATH=${MSYS_WIN}/mingw64/bin
export PATH=/g/Rust/cargo/bin:/mingw64/bin:$PATH
# MSYSTEM=MINGW64 points pkg-config at MINGW64's .pc files; the CLANG64 host build then took MINGW64's headers
# (-isystem .../mingw64/include before libc++, 2026-10-17). The host tools read CLANG64's; the Switch side has its own
# pkg-config wrapper (switch-pkg-config-wrapper.sh).
export PKG_CONFIG_PATH="${MSYS_REAL}/clang64/lib/pkgconfig;${MSYS_REAL}/clang64/share/pkgconfig"
export PKG_CONFIG_SYSTEM_INCLUDE_PATH="${MSYS_REAL}/clang64/include"
export PKG_CONFIG_SYSTEM_LIBRARY_PATH="${MSYS_REAL}/clang64/lib"
# Meson finds LLVM through CMake, which searched PATH and took MINGW64's LLVMConfig (-isystem .../mingw64/include).
export CMAKE_PREFIX_PATH="${MSYS_REAL}/clang64"
# Problems 1 and 2: the checkout carries the patch (dirty), so the release guard is lifted and the date given.
export ALLOW_DIRTY=1
export SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(git show -s --format=%ct HEAD)}
./build-unified.sh
find mesa-unified-install \( -name "libvulkan.a" -o -name "libnvk.a" \) -exec ls -la {} \;
