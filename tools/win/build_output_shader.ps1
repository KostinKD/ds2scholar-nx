# Rebuilds app/src/me/native/shaders/sa2_output_ramp_gamma_ps.h from sa2_output_ramp_gamma.frag (the output pass with
# the game's gamma ramp and FXAA). glslangValidator comes from the PC build (out/glslang).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\win\build_output_shader.ps1
param([string]$Glslang = 'out\glslang\StandAlone\glslangValidator.exe')
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $root
$src = 'app\src\me\native\shaders\sa2_output_ramp_gamma.frag'
$out = 'app\src\me\native\shaders\sa2_output_ramp_gamma_ps.h'
& $Glslang -V --vn sa2_output_ramp_gamma_ps -o $out $src
if ($LASTEXITCODE -ne 0) { throw "glslangValidator failed ($LASTEXITCODE)" }
"written $out"
