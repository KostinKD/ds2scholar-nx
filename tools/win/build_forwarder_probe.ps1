param([string]$Output = 'out/forwarder-probe')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$sdk = if ($env:DEVKITPRO) { $env:DEVKITPRO } else { 'G:/devkitPro' }
$dest = [IO.Path]::GetFullPath((Join-Path $root $Output))
New-Item -ItemType Directory -Force $dest | Out-Null
$elf = Join-Path $dest 'forwarder-icon-probe.elf'
& "$sdk/devkitA64/bin/aarch64-none-elf-gcc.exe" -O2 -Wall -Wextra -march=armv8-a -mtune=cortex-a57 -mtp=soft -fPIE -D__SWITCH__ "-I$sdk/libnx/include" "-specs=$sdk/libnx/switch.specs" (Join-Path $root 'tools/switch/forwarder_icon_probe.c') "-L$sdk/libnx/lib" -lnx -o $elf
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$nacp = Join-Path $dest 'forwarder-icon-probe.nacp'
& "$sdk/tools/bin/nacptool.exe" --create 'DS2 HOME icon probe' 'ds2scholar-nx' '0.1.0' $nacp
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$nro = Join-Path $dest 'forwarder-icon-probe.nro'
& "$sdk/tools/bin/elf2nro.exe" $elf $nro "--icon=$sdk/libnx/default_icon.jpg" "--nacp=$nacp"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Get-Item $nro | Select-Object Name,Length
