param(
    [string]$VivadoRoot = "C:\Xilinx\Vivado\2022.2",
    [string]$Receipt = ""
)

$ErrorActionPreference = "Stop"
$fpgaRoot = Split-Path -Parent $PSScriptRoot
$manifestPath = Join-Path $fpgaRoot "output\artifact_manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw "Build manifest not found; run build_bitstream.ps1 first"
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$bit = Join-Path $fpgaRoot "zcu106_cell_control\build\zcu106_adc_capture.bit"
$ltx = Join-Path $fpgaRoot "zcu106_cell_control\build\zcu106_adc_capture.ltx"
$actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $bit).Hash.ToLowerInvariant()
$expected = $manifest.artifacts.'zcu106_adc_capture.bit'
if ($actual -ne $expected) {
    throw "Bitstream does not match artifact_manifest.json"
}
$actualProbes = (Get-FileHash -Algorithm SHA256 -LiteralPath $ltx).Hash.ToLowerInvariant()
$expectedProbes = $manifest.artifacts.'zcu106_adc_capture.ltx'
if ($actualProbes -ne $expectedProbes) {
    throw "Probes file does not match artifact_manifest.json"
}
if ([string]::IsNullOrWhiteSpace($Receipt)) {
    $Receipt = Join-Path $fpgaRoot "output\deployment_receipt.json"
}
$vivado = Join-Path $VivadoRoot "bin\vivado.bat"
$script = Join-Path $PSScriptRoot "program_bitstream.tcl"
& $vivado -mode batch -source $script -tclargs `
    $bit $ltx $expected $expectedProbes $Receipt
if ($LASTEXITCODE -ne 0) { throw "Safe bitstream programming failed" }
