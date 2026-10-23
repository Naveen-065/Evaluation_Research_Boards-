param(
    [string]$SenseEvalUrl = 'http://127.0.0.1:8771',
    [string]$ZesHost = '',
    [int]$ZesPort = 9106
)

$ErrorActionPreference = 'Continue'
$projectRoot = Split-Path -Parent $PSScriptRoot
$vivado = 'C:\Xilinx\Vivado\2022.2\bin\vivado.bat'
$aarch64Gcc = 'C:\Xilinx\Vitis\2022.2\gnu\aarch64\nt\aarch64-linux\bin\aarch64-linux-gnu-gcc.exe'
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$pythonExe = if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $venvPython } else { 'python' }

$checks = [System.Collections.Generic.List[object]]::new()
function Add-Check([string]$Name, [bool]$Ready, [string]$Detail) {
    $checks.Add([pscustomobject]@{Component=$Name; Ready=$Ready; Detail=$Detail})
}

try {
    $pythonText = (& $pythonExe -c 'import sys; print(sys.version.split()[0])' 2>&1 | Out-String).Trim()
    Add-Check 'Python web runtime' ($LASTEXITCODE -eq 0) $pythonText
} catch {
    Add-Check 'Python web runtime' $false $_.Exception.Message
}

Add-Check 'Vivado 2022.2' (Test-Path -LiteralPath $vivado -PathType Leaf) $vivado
Add-Check 'AArch64 Linux compiler' (Test-Path -LiteralPath $aarch64Gcc -PathType Leaf) $aarch64Gcc

try {
    $status = Invoke-RestMethod -Uri "$SenseEvalUrl/api/status" -TimeoutSec 5
    $detail = "target=$($status.target), revision=$($status.api_revision), busy=$($status.busy), ready=$($status.deployment.ready)"
    Add-Check 'Existing SenseEval API' ($status.target -eq 'zcu106' -and $status.deployment.ready) $detail
} catch {
    Add-Check 'Existing SenseEval API' $false $_.Exception.Message
}

$modelPath = [Environment]::GetEnvironmentVariable('QWEN_MODEL_PATH')
if (-not $modelPath) {
    $candidateModel = Join-Path $projectRoot 'models\Qwen3-0.6B'
    if (Test-Path -LiteralPath $candidateModel -PathType Container) {
        $modelPath = $candidateModel
    }
}
$modelWeight = if ($modelPath) { Join-Path $modelPath 'model.safetensors' } else { '' }
$modelReady = $modelPath -and
    (Test-Path -LiteralPath (Join-Path $modelPath 'config.json') -PathType Leaf) -and
    (Test-Path -LiteralPath $modelWeight -PathType Leaf) -and
    ((Get-Item -LiteralPath $modelWeight).Length -gt 1000000000)
Add-Check 'Local Qwen model' ([bool]$modelReady) $(if ($modelPath) {$modelPath} else {'no local model directory found'})

try {
    & $pythonExe -c 'import torch, transformers' 2>$null
    Add-Check 'Torch + Transformers' ($LASTEXITCODE -eq 0) $(if ($LASTEXITCODE -eq 0) {'installed'} else {'not installed for this Python'})
} catch {
    Add-Check 'Torch + Transformers' $false 'not installed for this Python'
}

if ($ZesHost) {
    $probe = Test-NetConnection -ComputerName $ZesHost -Port $ZesPort -WarningAction SilentlyContinue
    Add-Check 'ZCU106 A53 ZES relay' $probe.TcpTestSucceeded "$ZesHost`:$ZesPort"
} else {
    Add-Check 'ZCU106 A53 ZES relay' $false 'Pass -ZesHost after Linux and the relay are deployed.'
}

$bitstream = Join-Path $projectRoot 'fpga\zcu106_cell_control\build\zcu106_adc_capture.bit'
$probes = Join-Path $projectRoot 'fpga\zcu106_cell_control\build\zcu106_adc_capture.ltx'
Add-Check 'Bitmap FPGA image' ((Test-Path -LiteralPath $bitstream -PathType Leaf) -and
    (Test-Path -LiteralPath $probes -PathType Leaf)) "$bitstream; $probes"

$checks | Format-Table -AutoSize

$required = $checks | Where-Object {$_.Component -in @('Python web runtime','Vivado 2022.2','AArch64 Linux compiler','Bitmap FPGA image')}
if ($required.Ready -contains $false) {
    exit 1
}

