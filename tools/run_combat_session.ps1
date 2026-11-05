# Launch online_pair with coop_combat_probe
$ErrorActionPreference = "Stop"

$pairCmd = "python tools/online_pair.py --seconds 900 --shot-every 5 --runtime-dir sdk/out/win-amd64 --seed out/bot_pair/seed_heide_ready_20261026 --p2p-lan --p2p-title-identity --p2p-diagnostics --p2p-guest-log --p2p-game-trace --p2p-name-trace --user-name-lookup --script '88:start,105:a,130:a,145:a,175:a'"

Write-Host "Starting online_pair probe..."
$pairJob = Start-Process -FilePath "python" -ArgumentList "tools/online_pair.py", "--seconds", "900", "--shot-every", "5", "--runtime-dir", "sdk/out/win-amd64", "--seed", "out/bot_pair/seed_heide_ready_20261026", "--p2p-lan", "--p2p-title-identity", "--p2p-diagnostics", "--p2p-guest-log", "--p2p-game-trace", "--p2p-name-trace", "--user-name-lookup", "--script", "88:start,105:a,130:a,145:a,175:a" -PassThru

Write-Host "online_pair PID: $($pairJob.Id)"

# Wait for run folder to appear
Start-Sleep -Seconds 3
$latestRun = Get-ChildItem out/bot_pair -Directory | Where-Object { $_.Name -match "^\d{8}_\d{6}$" } | Sort-Object CreationTime -Descending | Select-Object -First 1

if (-not $latestRun) {
    Write-Error "Failed to locate run directory under out/bot_pair"
    exit 1
}

Write-Host "Detected run directory: $($latestRun.FullName)"

# Launch probe
python tools/coop_combat_probe.py $latestRun.FullName --re-summon

# Wait for pairJob to exit
$pairJob.WaitForExit()
Write-Host "Session probe completed with exit code: $($pairJob.ExitCode)"
