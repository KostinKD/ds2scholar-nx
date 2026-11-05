# Run through tools/win/run.ps1; only the small forwarder is built, not the game.
param(
    [string]$Nro = '',
    [string]$Keys = $env:SWITCH_PROD_KEYS,
    [string]$Deps = '',
    [string]$Output = '',
    [string]$Icon = '',
    [ValidateSet(2,3)][int]$MaxCpu = 3
)
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$argsList = @('-I', (Join-Path $root 'tools\forwarder.py'), '--max-cpu', "$MaxCpu")
foreach ($pair in @(@('--nro',$Nro),@('--keys',$Keys),@('--deps',$Deps),@('--output',$Output),@('--icon',$Icon))) {
    if ($pair[1]) { $argsList += @($pair[0],$pair[1]) }
}
& python @argsList
exit $LASTEXITCODE
