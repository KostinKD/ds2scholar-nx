# Starts the PC build to PLAY (stage 3: Majula and the first bosses by hand): sound on, a normal window, saves in
# out\pc\userdata (not the OneDrive-synced Documents folder the SDK uses by default), and a still image every
# -ShotEvery seconds in out\pc\captures (shot_<s>s.ppm; tools\ppm_to_png.py), so a log can be matched to a place.
# Everything is set through the environment for this run only: ds2.toml and the test defaults (muted, minimized) stay.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\win\play.ps1               a controller (SDL)
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\win\play.ps1 -Keyboard     keyboard and mouse too
#
# The log is out\pc\logs\ds2_NNN.log (the newest one); this script prints its name and its errors when the game ends.
param(
    [string]$Exe = 'out\pc\ds2.exe',
    [int]$ShotEvery = 60,
    [switch]$Keyboard,
    # Sound checks (2026-10-16: silent on an 8-channel headset although the game's mix is not):
    #   -Stereo     fold 5.1 to stereo before the device (SDK cvar audio_force_stereo)
    #   -AudioDump  the first N seconds of what goes to the device, from -AudioDumpFrom on, in out\pc\audio_output.wav
    [switch]$Stereo,
    [int]$AudioDump = 0,
    [int]$AudioDumpFrom = 60
)
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$exePath = (Resolve-Path (Join-Path $root $Exe)).Path
$dir = Split-Path $exePath

$env:REX_AUDIO_MUTE = 'false'
$env:REX_WINDOW_START_MINIMIZED = 'false'
$env:REX_USER_DATA_ROOT = Join-Path $dir 'userdata'
$env:REX_DS2_SHOT_EVERY_S = "$ShotEvery"
if ($Keyboard) { $env:REX_MNK_MODE = 'true' }
if ($Stereo) { $env:REX_AUDIO_FORCE_STEREO = 'true' }
if ($AudioDump -gt 0) {
    $env:REX_AUDIO_DUMP_OUTPUT_S = "$AudioDump"
    $env:REX_AUDIO_DUMP_OUTPUT_FROM_S = "$AudioDumpFrom"
}

$started = Get-Date
"Playing $exePath (saves in $env:REX_USER_DATA_ROOT, a shot every $ShotEvery s). Close the window to stop."
$p = Start-Process -FilePath $exePath -WorkingDirectory $dir -PassThru
$p.WaitForExit()
'{0} exited after {1:n0} s with code 0x{2:X8}' -f (Split-Path $exePath -Leaf), ((Get-Date) - $started).TotalSeconds, $p.ExitCode

$log = Get-ChildItem (Join-Path $dir 'logs') -Filter *.log -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -ge $started.AddSeconds(-2) } | Sort-Object LastWriteTime | Select-Object -Last 1
if ($log) {
    "== $($log.FullName)"
    # The errors, without the known cache:/install: device misses (docs/progress.md).
    # The audio device and the game's own mix level (peak of the 10 s lines: 0 means the game itself was silent).
    Select-String -Path $log.FullName -Pattern 'audio endpoint|guest peak|SDL output dump' | Select-Object -First 1 -Last 3 |
        ForEach-Object { $_.Line }
    Select-String -Path $log.FullName -Pattern '\[error\]|FATAL|unregistered|Unresolved' |
        Where-Object { $_.Line -notmatch 'cache:|install:' } | Select-Object -Last 20 | ForEach-Object { $_.Line }
}
