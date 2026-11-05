# Stage 4: A/B of native renderer cvars on the Majula save (2026-10-16). Like majula_sweep.ps1, but with
# sa2_renderer_native on and a run = a set of cvars ("a=1;b=2"), so whole groups can be switched off and bisected.
# Prints the saturated-yellow share of the shot (tools\yellow_metric.py). Muted and minimized (boot_test.ps1).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\win\native_ab.ps1 -Runs "baseline|sa2_native_z_early=false;..."
param(
    [string]$Runs = 'baseline',
    [int]$At = 112,
    [string]$Backup = 'out\userdata_backup_majula',
    [string]$Script = '28:start,50:a,58:a,66:a,72:a,80:a,86:a'
)
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $root
$userdata = Join-Path $root 'out\pc\userdata'
$i = 0
foreach ($run in ($Runs -split '\|' | Where-Object { $_.Trim() })) {
    $i++
    Copy-Item -Recurse -Force (Join-Path $root "$Backup\B13EBABEBABEBABE\*") (Join-Path $userdata 'B13EBABEBABEBABE')  # the save only
    $env:REX_USER_DATA_ROOT = $userdata
    $env:REX_DS2_INPUT_SCRIPT = $Script
    $env:REX_DS2_SHOT_S = "$At"
    $env:REX_SA2_RENDERER_NATIVE = 'true'
    $set = @()
    if ($run.Trim() -ne 'baseline') {
        foreach ($kv in ($run -split ';' | Where-Object { $_.Trim() })) {
            $name, $value = $kv.Trim().Split('=', 2)
            Set-Item -Path "env:REX_$($name.ToUpper())" -Value $value
            $set += "REX_$($name.ToUpper())"
        }
    }
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\win\boot_test.ps1 -Exe out\pc\ds2.exe -Seconds ($At + 3) -Tail 0 | Out-Null
    foreach ($n in $set) { Remove-Item -Path "env:$n" -ErrorAction SilentlyContinue }
    Remove-Item env:REX_USER_DATA_ROOT, env:REX_DS2_INPUT_SCRIPT, env:REX_DS2_SHOT_S, env:REX_SA2_RENDERER_NATIVE -ErrorAction SilentlyContinue
    $kept = Join-Path $root "out\pc\captures\ab_$i.ppm"
    Copy-Item -Force (Join-Path $root "out\pc\captures\shot_${At}s.ppm") $kept
    $metric = python -I tools\yellow_metric.py $kept
    "{0,-3} {1} | {2}" -f $i, ($metric -replace '^.*: ', ''), $run
}
Copy-Item -Recurse -Force (Join-Path $root "$Backup\B13EBABEBABEBABE\*") (Join-Path $userdata 'B13EBABEBABEBABE')
