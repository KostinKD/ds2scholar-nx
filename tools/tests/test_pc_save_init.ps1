$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$source = Get-Content -Raw (Join-Path $repo 'tools\play_host.ps1')
$start = $source.IndexOf('# Initialize missing profiles')
$end = $source.IndexOf('# Shared title update content', $start)
if ($start -lt 0 -or $end -lt $start) { throw 'Save initialization block not found' }
$block = $source.Substring($start, $end - $start)
if ($block.Contains('Start-Process') -or $block.Contains('Stop-Process')) { throw 'Unsafe test block' }
$root = Join-Path $repo ('out\invasion_orbs\launcher_test_' + [guid]::NewGuid().ToString('N'))
$build = Join-Path $root 'build'
$switchXuid = 'B13EBABEBABEBABE'
$pcXuid = 'B13EBABEBABEBAC0'
$fakeSeed = Join-Path $root "out\bot_pair\seed_heide_ready_20261026\$switchXuid\465307E4\00000001\-GAME_0000"
$partialSave = Join-Path $build "userdata\$pcXuid\465307E4\00000001\-GAME_0000"
New-Item -ItemType Directory -Force $fakeSeed, $partialSave | Out-Null
Set-Content -LiteralPath (Join-Path $fakeSeed 'USER_DATA01') -Value 'seed01'
Set-Content -LiteralPath (Join-Path $fakeSeed 'USER_DATA02') -Value 'seed02'
Set-Content -LiteralPath (Join-Path $partialSave 'USER_DATA02') -Value 'keep-existing-character'
& ([scriptblock]::Create($block))
if ((Get-Content -Raw (Join-Path $partialSave 'USER_DATA02')).Trim() -ne 'keep-existing-character') {
    throw 'Existing character was overwritten'
}
if (Test-Path (Join-Path $partialSave 'USER_DATA01')) { throw 'Existing partial save was modified' }
$initialized = Join-Path $build "userdata\$switchXuid\465307E4\00000001\-GAME_0000\USER_DATA01"
if ((Get-Content -Raw $initialized).Trim() -ne 'seed01') { throw 'Missing save was not initialized' }
Write-Output 'PASS: missing save initialized; existing partial save preserved'
