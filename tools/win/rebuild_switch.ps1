# One command for a checked PGO+LTO rebuild. Toolchain/game/PGO setup: docs/rebuild.md.
param(
    [ValidateRange(1, 5)][int]$Jobs = 5,
    [string]$BuildDir = 'out/nx_pgo',
    [string]$PgoDir = 'pgo',
    [switch]$Regenerate,
    [switch]$Clean,
    [switch]$Plan
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Set-Location $root
if (-not $env:SA2_LLVM -and (Test-Path 'G:/Program Files/LLVM')) { $env:SA2_LLVM = 'G:/Program Files/LLVM' }
if (-not $env:SA2_VSDIR -and (Test-Path 'G:/Program Files/VisualStudio')) { $env:SA2_VSDIR = 'G:/Program Files/VisualStudio' }
if (-not $env:DEVKITPRO -or -not (Test-Path $env:DEVKITPRO)) {
    if (Test-Path 'G:/devkitPro') { $env:DEVKITPRO = 'G:/devkitPro' }
}
foreach ($path in @($BuildDir, $PgoDir)) {
    if ($path.Contains('"')) { throw 'A path cannot contain a quote' }
}
$command = "python -I tools/rebuild_switch.py --jobs $Jobs --build-dir `"$BuildDir`" --pgo-dir `"$PgoDir`""
if ($Regenerate) { $command += ' --regenerate' }
if ($Clean) { $command += ' --clean' }
if ($Plan) { $command += ' --plan' }
$log = 'logs/rebuild_switch_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.log'
Write-Host "Full log: $root/$log"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'run.ps1') $log $command
exit $LASTEXITCODE
