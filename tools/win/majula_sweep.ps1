# Stage 3: A/B of GPU cvars on Majula's black sky (2026-10-16). Each run restores the save from -Backup (the owner's
# save at the Majula bonfire), loads it with a scripted pad (title -> Start -> 2x A -> Continue -> confirm), saves a
# shot at -At seconds and measures the near-black share of the sky band (tools\shot_metric.py). Muted and minimized
# (tools\win\boot_test.ps1). One cvar=value per run, plus a baseline run first.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\win\majula_sweep.ps1 -Cvars "depth_float24_round=true,..."
param(
    [string]$Cvars = '',
    [int]$At = 112,
    [string]$Backup = 'out\userdata_backup_majula',
    [string]$Script = '28:start,50:a,58:a,66:a,72:a'
)
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $root
$userdata = Join-Path $root 'out\pc\userdata'
$runs = @('baseline') + ($Cvars -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
foreach ($run in $runs) {
    Copy-Item -Recurse -Force (Join-Path $root "$Backup\B13EBABEBABEBABE\*") (Join-Path $userdata 'B13EBABEBABEBABE')  # the save only: the shader cache must not roll back
    $env:REX_USER_DATA_ROOT = $userdata
    $env:REX_DS2_INPUT_SCRIPT = $Script
    $env:REX_DS2_SHOT_S = "$At"
    $name = $null
    if ($run -ne 'baseline') {
        $name, $value = $run.Split('=', 2)
        Set-Item -Path "env:REX_$($name.ToUpper())" -Value $value
    }
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\win\boot_test.ps1 -Exe out\pc\ds2.exe -Seconds ($At + 3) -Tail 0 | Out-Null
    if ($name) { Remove-Item -Path "env:REX_$($name.ToUpper())" -ErrorAction SilentlyContinue }
    Remove-Item env:REX_USER_DATA_ROOT, env:REX_DS2_INPUT_SCRIPT, env:REX_DS2_SHOT_S -ErrorAction SilentlyContinue
    $shot = Join-Path $root "out\pc\captures\shot_${At}s.ppm"
    $safe = ($run -replace '[^A-Za-z0-9_=.-]', '_') -replace '=', '-'
    $kept = Join-Path $root "out\pc\captures\sweep_$safe.ppm"
    Copy-Item -Force $shot $kept
    $metric = python -I tools\shot_metric.py $kept
    "{0,-50} {1}" -f $run, ($metric -replace '^.*: ', '')
}
Copy-Item -Recurse -Force (Join-Path $root "$Backup\B13EBABEBABEBABE\*") (Join-Path $userdata 'B13EBABEBABEBABE')  # the save only: the shader cache must not roll back
