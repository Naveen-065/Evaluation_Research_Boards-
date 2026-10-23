param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8780,
    [string]$ModelPath = '',
    [string]$ZesHost = '',
    [switch]$ExclusiveHardware
)

$ErrorActionPreference = "Stop"
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $appRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$pythonExe = if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $venvPython } else { 'python' }

if (-not $ModelPath) {
    $bundledModel = Join-Path $projectRoot 'models\Qwen3-0.6B'
    $weightFile = Join-Path $bundledModel 'model.safetensors'
    if ((Test-Path -LiteralPath (Join-Path $bundledModel 'config.json') -PathType Leaf) -and
        (Test-Path -LiteralPath $weightFile -PathType Leaf) -and
        ((Get-Item -LiteralPath $weightFile).Length -gt 1000000000)) {
        $ModelPath = $bundledModel
    }
}

if ($ModelPath) {
    $resolvedModel = (Resolve-Path -LiteralPath $ModelPath).Path
    $env:QWEN_MODEL_PATH = $resolvedModel
}
if ($ZesHost) {
    $env:ZES_EDAC_HOST = $ZesHost
}
if ($ExclusiveHardware) {
    $env:RERAM_EXCLUSIVE_HARDWARE = '1'
}

Set-Location -LiteralPath $appRoot
Write-Host "SenseEval Qwen/ZES GUI: http://127.0.0.1:$Port/"
Write-Host "Python: $pythonExe"
Write-Host "Model: $(if ($env:QWEN_MODEL_PATH) { $env:QWEN_MODEL_PATH } else { 'deterministic fallback (Qwen weights not ready)' })"
Write-Host "Direct FPGA mode: $(if ($env:RERAM_EXCLUSIVE_HARDWARE -eq '1') { 'exclusive (legacy port 8771 must be closed)' } else { 'disabled' })"
& $pythonExe server.py --port $Port

