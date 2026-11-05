# Builds the Nintendo Switch NRO: out\nx\ds2.nro (devkitA64 GCC + libnx, static NVK from the Mesa Horizon SDK).
# The generated code must already exist (tools\codegen.ps1 with the PC SDK): a cross build cannot run rexglue.
# From sa2-nx's script, for this machine (docs/progress.md, stage 5): MSYS2 at G:\msys64 with devkitPro's switch-dev in
# its /opt/devkitpro (junction G:\devkitPro), NVK from tools/switch/build_nvk_msys2.sh.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\win\build_switch.ps1 [-Jobs 8] [-Reconfigure]
#       [-BuildDir out\nx_lto] [-Define DS2_SWITCH_LTO=ON,DS2_SWITCH_LTO_JOBS=6]
# NVK_SDK / DEVKITPRO (environment) override the Mesa SDK folder (it must contain lib\libvulkan.a) and devkitPro.
# -BuildDir: one folder per build variant, so switching flags does not rebuild everything (ds2scholar-nx 2026-10-21).
# -Define: extra -D cache entries, applied on (re)configure.
param(
    [int]$Jobs = 8,
    [switch]$Reconfigure,
    [string]$BuildDir = 'out\nx',
    [string[]]$Define = @()
)
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $PSScriptRoot 'env.ps1')  # VS CMake and Ninja on PATH (the compilers come from the toolchain file)
$nvk = if ($env:NVK_SDK) { $env:NVK_SDK } else {
    'G:/DS2Switch/mesa-switch/mesa-unified-install/opt/devkitpro/portlibs/switch' }
# devkitPro's MSYS2 exports DEVKITPRO as an MSYS path (/opt/devkitpro) that Windows CMake cannot open.
$devkitpro = if ($env:DEVKITPRO -and (Test-Path $env:DEVKITPRO)) { $env:DEVKITPRO } else { 'G:/devkitPro' }
# CMake's try_compile re-reads the toolchain file without -DDEVKITPRO and falls back to the environment variable.
$env:DEVKITPRO = $devkitpro
# GCC's lto-wrapper runs the LTRANS jobs of -flto=N through GNU make; without one it compiles them one after another
# ("serial compilation of 512 LTRANS jobs": ds2-nx's 38-minute link). It takes the program from MAKE. GNU make 4.4.1
# from MSYS2 (pacman -S make, 2026-10-21); only MAKE is set, G:\msys64\usr\bin stays off PATH (its own link/find).
$make = if ($env:DS2_GNU_MAKE) { $env:DS2_GNU_MAKE } else { 'G:/msys64/usr/bin/make.exe' }
if (Test-Path $make) { $env:MAKE = $make } else { Write-Warning "GNU make not found at ${make}: LTRANS jobs will run serially" }
$build = Join-Path $root $BuildDir
$glslang = Join-Path $root 'out\glslang\StandAlone\glslangValidator.exe'  # host tool: SPIR-V is portable
if ($Reconfigure -or -not (Test-Path (Join-Path $build 'CMakeCache.txt'))) {
    # powershell -File passes "A=1,B=2" as one string: split it here.
    $extra = @(($Define -join ",") -split "," | Where-Object { $_ } | ForEach-Object { "-D$_" })
    & cmake -S (Join-Path $root 'app') -B $build -G Ninja -DCMAKE_BUILD_TYPE=Release `
        "-DCMAKE_TOOLCHAIN_FILE=$root\tools\switch\cmake\switch-devkitA64.cmake" `
        "-DREXGLUE_SWITCH_NVK_SDK=$nvk" "-DDS2_GLSLANG_VALIDATOR=$glslang" "-DDEVKITPRO=$devkitpro" `
        "-DCMAKE_MAKE_PROGRAM=$((Get-Command ninja).Source)" @extra
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
}
& cmake --build $build -j $Jobs
exit $LASTEXITCODE
