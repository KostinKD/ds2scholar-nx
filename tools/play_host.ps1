# Starts PC Host in interactive GUI mode for the user to play directly
param(
    [switch]$NoAutoBoot,
    # Online server: the VPS (docs/online-server.md); -ServerIp 192.168.1.95 for the LAN server on this PC
    [string]$ServerIp = "185.99.98.178",
    # P2P through the server relay (docs/online-relay.md); -NoRelay for the direct LAN pair
    [switch]$NoRelay
)

$root = (Resolve-Path "$PSScriptRoot\..").Path
$build = Join-Path $root "out\pc"
$exePath = Join-Path $build "ds2.exe"

$switchIp = "192.168.1.76"
$pcIp = "192.168.1.95"
$switchXuid = "B13E98C73B92CE1D"   # from the Switch user account (net_profile_generate_xuid, 2026-10-28)
$pcXuid = "B13EBABEBABEBAC0"

# Kill any lingering background ds2.exe
Get-Process -Name "ds2" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500

# Copy latest SDK runtime DLLs if available
$runtimeDir = Join-Path $root "sdk\out\win-amd64"
if (Test-Path $runtimeDir) {
    Copy-Item -Force (Join-Path $runtimeDir "rexruntimerd.dll") $build
    Copy-Item -Force (Join-Path $runtimeDir "rexgpu-xenosrd.dll") $build
}

# Initialize missing profiles; preserve existing characters and inventory.
# The seed save was captured under the default XUID; it stays there whatever the Switch XUID is now.
$seedSource = Join-Path $root "out\bot_pair\seed_heide_ready_20261026\B13EBABEBABEBABE\465307E4\00000001"
@($switchXuid, $pcXuid) | ForEach-Object {
    $dir = Join-Path $build "userdata\$_\465307E4\00000001"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    if (-not (Test-Path (Join-Path $dir '-GAME_0000'))) {
        Copy-Item -Recurse -Force (Join-Path $seedSource "*") $dir
    }
}

# Shared title update content
$sharedContent = Join-Path $root "out\bot_pair\seed_heide_ready_20261026\0000000000000000"
$link = Join-Path $build "userdata\0000000000000000"
if ((Test-Path $sharedContent) -and (-not (Test-Path $link))) {
    cmd /c mklink /J "$link" "$sharedContent" | Out-Null
}

# Audio & Window settings (Full normal window with sound)
$env:REX_AUDIO_MUTE = "false"
$env:REX_WINDOW_START_MINIMIZED = "false"
$env:REX_GAME_DATA_ROOT = Join-Path $root "assets\game_root"
$env:REX_USER_DATA_ROOT = Join-Path $build "userdata"
$env:REX_CONTENT_BACKUP_ROOT = ""

# Controls: Keyboard + Mouse & Gamepad
$env:REX_MNK_MODE = "true"
$env:REX_MNK_MOUSE = "true"
$env:REX_KEYBIND_A = "Space,Return,E,LMB"
$env:REX_KEYBIND_B = "Backspace,Escape,Q,RMB"
$env:REX_KEYBIND_X = "R,F"
$env:REX_KEYBIND_Y = "Y,C"
$env:REX_KEYBIND_START = "Return,Escape"
$env:REX_KEYBIND_BACK = "Tab,Z"
$env:REX_NET_PROBE_INPUT_FILE = Join-Path $build "pad.txt"

# P2P & DS3OS Networking
$env:REX_NET_PROFILE_XUID = [string][UInt64]::Parse($pcXuid, [System.Globalization.NumberStyles]::HexNumber)
$env:REX_NET_ONLINE_PROBE = "true"
$env:REX_NET_DNS_ADDRESS = $ServerIp
$env:REX_NET_TITLE_SERVER_COUNT = "1"
$env:REX_NET_P2P_DIAGNOSTICS = "true"
$env:REX_NET_P2P_GUEST_LOG = "true"
$env:REX_NET_P2P_GAME_TRACE = "true"
$env:REX_NET_P2P_NAME_TRACE = "true"
$env:REX_NET_USER_NAME_LOOKUP = "true"
$env:REX_NET_CLIENT_HELLO = "true"   # client protocol for the server (X360MinClientProtocol)
$env:REX_NET_NAME_SERVICE = "true"   # gamertags of other players from the server (X360NameService)
$env:REX_NET_USER_NAME_DIRECTORY = "$pcXuid=User"   # the Switch name comes from the server (net_name_service)
$env:REX_NET_P2P_LAN = "true"
$env:REX_NET_P2P_TITLE_IDENTITY = "true"
$env:REX_NET_P2P_SESSION_ADDRESSES = "true"
$env:REX_NET_P2P_RELAY = $(if ($NoRelay) { "false" } else { "true" })
$env:REX_NET_P2P_ACTIVE_SESSION_KEY = "true"
$env:REX_NET_P2P_ADDRESS = $pcIp
$env:REX_NET_P2P_PEER_ADDRESS = $switchIp
$env:REX_NET_P2P_PEER_XUID = [string][UInt64]::Parse($switchXuid, [System.Globalization.NumberStyles]::HexNumber)
$env:REX_NET_P2P_PORT = "3074"
$env:REX_DS2_SOCKET_BUFFER_ENDIAN = "true"
$env:REX_SA2_RENDERER_NATIVE = "false"

if (-not $NoAutoBoot) {
    # Auto-load save into Heide Ruin Bonfire
    $env:REX_DS2_INPUT_SCRIPT = "88:start,105:a,130:a,145:a,175:a"
}

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "Starting interactive Dark Souls II Host Window on desktop!" -ForegroundColor Green
Write-Host "Controls: Gamepad (Xbox/DualShock) or Keyboard + Mouse" -ForegroundColor Cyan
Write-Host "  - Select/Action (A): Space / Enter / E" -ForegroundColor Yellow
Write-Host "  - Back/Roll (B):     Backspace / Escape / Q" -ForegroundColor Yellow
Write-Host "  - Move (Stick):      W, A, S, D" -ForegroundColor Yellow
Write-Host "  - Menu (Start):      Enter" -ForegroundColor Yellow
Write-Host "Auto-loading into Heide's Tower of Flame..." -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Green

$p = Start-Process -FilePath $exePath -WorkingDirectory $build -PassThru
$p.WaitForExit()
