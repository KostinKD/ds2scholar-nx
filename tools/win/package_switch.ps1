# Lays out the Switch SD card folder in out\nx\sdcard\switch\ds2scholar-nx: the NRO, its settings (app\ds2_switch.toml as
# ds2.toml) and the native renderer's shader package (out\pc\sa2_shaders.mesp + .idx, the one the PC runs test).
# The game files are yours and stay out of the repository:
#   -IncludeGame   copies assets\game_root as a loose folder (121 files, 5.8 GB, the largest 2.8 GB: fits FAT32;
#                  one asset pack would not, docs/progress.md stage 5).
# By hand: sdmc:/switch/ds2scholar-nx/game_root/  <- assets\game_root
#   -IncludeCompatPack  copies the extracted compatibility pack (DLC catalog, 1.2 GB; SotFS does not start without it,
#                  docs/analysis/files.md) to ds2\0000000000000000\465307E4\00000002\: the user data root on the console
#                  is <NRO folder>/ds2/ (ds2-nx console log 2026-10-20: saves in /switch/ds2-nx/ds2/B13EBABEBABEBABE/...).
# From sa2-nx's script (no enhancement configs, no A/B pair, no asset pack).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\win\package_switch.ps1 [-IncludeGame] [-IncludeCompatPack]
#
# -Public: the package for players (docs/online-public-plan.md, stage D) in out\release\<NRO version>\ and a zip next
# to it: the PGO NRO (out\nx_pgo), ds2.toml from tools\make_public_config.py (no owner LAN settings), the shader package
# that runs on the console (gpu lite2, out\shader_light2_v2; on the console since 2026-10-25), docs\players\README.md and
# extract-tools\ (god_extract.py, extract_iso.py, stfs_extract.py) to unpack the player's own game. Never game files.
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\win\package_switch.ps1 -Public
param([switch]$IncludeGame, [switch]$IncludeCompatPack, [switch]$Public, [string]$Nro = '', [string]$ShaderDir = '',
      [string]$ForwarderDir = '', [string]$ReleaseDir = '')
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $Nro) { $Nro = Join-Path $root $(if ($Public) { 'out\nx_pgo\ds2.nro' } else { 'out\nx\ds2.nro' }) }
if (-not $ShaderDir) { $ShaderDir = Join-Path $root $(if ($Public) { 'out\shader_light2_v2' } else { 'out\pc' }) }
if (-not (Test-Path $Nro)) { throw "no NRO at ${Nro}: run tools\win\build_switch.ps1 first" }
if ($Public) {
    if ($IncludeGame -or $IncludeCompatPack) { throw '-Public never includes game files' }
    $bundleArgs = @('-I',(Join-Path $root 'tools\release_bundle.py'),'--nro',$Nro,'--shader-dir',$ShaderDir)
    if ($ForwarderDir) { $bundleArgs += @('--forwarder-dir',$ForwarderDir) }
    if ($ReleaseDir) { $bundleArgs += @('--output',$ReleaseDir) }
    & python @bundleArgs
    exit $LASTEXITCODE
}
if ($ForwarderDir -or $ReleaseDir) { throw '-ForwarderDir and -ReleaseDir require -Public' }
$dest = Join-Path $root 'out\nx\sdcard\switch\ds2scholar-nx'
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item -Force $Nro (Join-Path $dest 'ds2.nro')
Copy-Item -Force (Join-Path $root 'app\ds2_switch.toml') (Join-Path $dest 'ds2.toml')
foreach ($f in 'sa2_shaders.mesp', 'sa2_shaders.mesp.idx') {
    Copy-Item -Force (Join-Path $ShaderDir $f) (Join-Path $dest $f)
}
if ($IncludeGame) {
    robocopy (Join-Path $root 'assets\game_root') (Join-Path $dest 'game_root') /E /NFL /NDL /NJH /NJS | Out-Null
}
if ($IncludeCompatPack) {
    $pack = '0000000000000000\465307E4\00000002'
    robocopy (Join-Path $root "assets\content\$pack") (Join-Path $dest "ds2\$pack") /E /NFL /NDL /NJH /NJS | Out-Null
}
Get-ChildItem $dest | Select-Object Name, Length
