# Stage 3 stutter A/B (2026-10-16): loads the owner's Majula save (as tools\win\majula_sweep.ps1) with the VdSwap count
# logged every second, and prints the seconds below 50 swaps and the worst second from -From to the end. Each run is
# "<label>|<cache>|<cvar=value;...>": cache "cold" uses an empty shader cache folder (cache_root), "warm" the normal one.
# Muted and minimized (tools\win\boot_test.ps1).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\win\stutter_ab.ps1 -Runs "A|cold|,B|warm|"
# (one comma-separated string: powershell -File passes a list as one argument)
param(
    [string]$Runs = 'cold default|cold|,warm default|warm|',
    [int]$Seconds = 125,
    [int]$From = 75,
    [string]$Backup = 'out\userdata_backup_majula',
    [string]$Script = '28:start,50:a,58:a,66:a,72:a'
)
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $root
$userdata = Join-Path $root 'out\pc\userdata'
foreach ($run in ($Runs -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })) {
    $label, $cache, $cvars = $run.Split('|', 3)
    Copy-Item -Recurse -Force (Join-Path $root "$Backup\B13EBABEBABEBABE\*") (Join-Path $userdata 'B13EBABEBABEBABE')  # the save only: the shader cache must not roll back
    $env:REX_USER_DATA_ROOT = $userdata
    $env:REX_DS2_INPUT_SCRIPT = $Script
    $env:REX_DS2_SWAP_LOG_S = '1'
    $set = @('REX_USER_DATA_ROOT', 'REX_DS2_INPUT_SCRIPT', 'REX_DS2_SWAP_LOG_S')
    if ($cache -eq 'cold') {
        $cold = Join-Path $root ("out\cold_cache_" + [guid]::NewGuid().ToString('N').Substring(0, 8))
        New-Item -ItemType Directory -Force $cold | Out-Null
        $env:REX_CACHE_ROOT = $cold
        $set += 'REX_CACHE_ROOT'
    }
    foreach ($kv in ($cvars -split ';' | Where-Object { $_ })) {
        $name, $value = $kv.Split('=', 2)
        Set-Item -Path "env:REX_$($name.ToUpper())" -Value $value
        $set += "REX_$($name.ToUpper())"
    }
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\win\boot_test.ps1 -Exe out\pc\ds2.exe -Seconds $Seconds -Tail 0 | Out-Null
    foreach ($v in $set) { Remove-Item -Path "env:$v" -ErrorAction SilentlyContinue }
    $log = (Get-ChildItem out\pc\logs\*.log | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
    $rates = @(Select-String -Path $log -Pattern '\[ds2\] VdSwap: (\d+) in' | ForEach-Object { [int]$_.Matches[0].Groups[1].Value })
    $tail = $rates | Select-Object -Skip ([Math]::Max(0, $From - 1))
    $below = @($tail | Where-Object { $_ -lt 50 }).Count
    $worst = ($tail | Measure-Object -Minimum).Minimum
    $zero = @($tail | Where-Object { $_ -eq 0 }).Count
    # Frame-to-frame gaps (ds2_swap_log.cpp polls every ms): the longest one and the count over 100 ms in the window.
    $gaps = @(Select-String -Path $log -Pattern 'longest gap (\d+) ms, gaps > 50 ms (\d+), > 100 ms (\d+)' |
        ForEach-Object { $_.Matches[0] }) | Select-Object -Skip ([Math]::Max(0, $From - 1))
    $longest = ($gaps | ForEach-Object { [int]$_.Groups[1].Value } | Measure-Object -Maximum).Maximum
    $over100 = ($gaps | ForEach-Object { [int]$_.Groups[3].Value } | Measure-Object -Sum).Sum
    $over50 = ($gaps | ForEach-Object { [int]$_.Groups[2].Value } | Measure-Object -Sum).Sum
    "{0,-24} s {1,3}: below 50/s {2,2}, worst {3,2}/s; longest gap {4,4} ms, gaps >50 ms {5,3}, >100 ms {6,3} ({7})" -f $label, $tail.Count, $below, $worst, $longest, $over50, $over100, (Split-Path $log -Leaf)
}
Copy-Item -Recurse -Force (Join-Path $root "$Backup\B13EBABEBABEBABE\*") (Join-Path $userdata 'B13EBABEBABEBABE')  # the save only: the shader cache must not roll back
