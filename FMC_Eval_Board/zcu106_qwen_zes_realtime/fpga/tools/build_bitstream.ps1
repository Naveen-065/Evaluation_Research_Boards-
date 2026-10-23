param(
    [string]$VivadoRoot = "C:\Xilinx\Vivado\2022.2",
    [switch]$ManifestOnly
)

$ErrorActionPreference = "Stop"
$fpgaRoot = Split-Path -Parent $PSScriptRoot
$vivado = Join-Path $VivadoRoot "bin\vivado.bat"
if (-not (Test-Path -LiteralPath $vivado)) {
    throw "Vivado not found: $vivado"
}

$output = Join-Path $fpgaRoot "output"
New-Item -ItemType Directory -Force -Path $output | Out-Null
$buildTcl = Join-Path $fpgaRoot "zcu106_cell_control\build_zcu106.tcl"
$buildLog = Join-Path $output "vivado_build.log"
$buildJournal = Join-Path $output "vivado_build.jou"
$scratch = Join-Path $env:TEMP "zcu106_bitmap_vivado"
New-Item -ItemType Directory -Force -Path $scratch | Out-Null
$previousScratch = $env:ZCU106_BITMAP_PROJECT_DIR
$env:ZCU106_BITMAP_PROJECT_DIR = $scratch

if (-not $ManifestOnly) {
    Push-Location $fpgaRoot
    try {
        & $vivado -mode batch -source $buildTcl -log $buildLog -journal $buildJournal
        if ($LASTEXITCODE -ne 0) {
            throw "Vivado build failed with exit code $LASTEXITCODE; see $buildLog"
        }
    }
    finally {
        Pop-Location
        if ($null -eq $previousScratch) {
            Remove-Item Env:ZCU106_BITMAP_PROJECT_DIR -ErrorAction SilentlyContinue
        }
        else {
            $env:ZCU106_BITMAP_PROJECT_DIR = $previousScratch
        }
    }
}
else {
    if ($null -eq $previousScratch) {
        Remove-Item Env:ZCU106_BITMAP_PROJECT_DIR -ErrorAction SilentlyContinue
    }
    else {
        $env:ZCU106_BITMAP_PROJECT_DIR = $previousScratch
    }
}

$buildDir = Join-Path $fpgaRoot "zcu106_cell_control\build"
$artifacts = @(
    "zcu106_adc_capture.bit",
    "zcu106_adc_capture.ltx",
    "zcu106_adc_capture.dcp",
    "timing_summary.rpt",
    "drc.rpt",
    "route_status.rpt",
    "io.rpt",
    "port_properties.tsv"
)
$hashes = [ordered]@{}
foreach ($name in $artifacts) {
    $path = Join-Path $buildDir $name
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Expected build artifact is missing: $path"
    }
    $hashes[$name] = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
}

$sourceHashes = [ordered]@{}
foreach ($sourceDirName in @("kc705_cell_control", "zcu106_cell_control")) {
    $sourceDir = Join-Path $fpgaRoot $sourceDirName
    $sources = Get-ChildItem -LiteralPath $sourceDir -File |
        Where-Object { $_.Extension -in ".v", ".xdc", ".tcl" } |
        Sort-Object Name
    foreach ($source in $sources) {
        $key = "$sourceDirName/$($source.Name)"
        $sourceHashes[$key] = (Get-FileHash -Algorithm SHA256 -LiteralPath $source.FullName).Hash.ToLowerInvariant()
    }
}

$hostToolHashes = [ordered]@{}
Get-ChildItem -LiteralPath (Join-Path $fpgaRoot "tools") -File |
    Where-Object { $_.Extension -in ".ps1", ".tcl", ".py" } |
    Sort-Object Name |
    ForEach-Object {
        $hostToolHashes["tools/$($_.Name)"] =
            (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
    }

$testHashes = [ordered]@{}
Get-ChildItem -LiteralPath (Join-Path $fpgaRoot "tests") -File |
    Where-Object { $_.Extension -in ".ps1", ".v" } |
    Sort-Object Name |
    ForEach-Object {
        $testHashes["tests/$($_.Name)"] =
            (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
    }

$manifest = [ordered]@{
    protocol = "ZCU106_BITMAP_V1"
    generated_utc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    artifact_build_utc = (Get-Item -LiteralPath (Join-Path $buildDir "zcu106_adc_capture.bit")).LastWriteTimeUtc.ToString("yyyy-MM-ddTHH:mm:ssZ")
    vivado = $VivadoRoot
    part = "xczu7ev-ffvc1156-2-e"
    top = "kc705_adc_test"
    bitstream_deployed = $false
    manifest_mode = $(if ($ManifestOnly) { "existing_artifacts_rehashed" } else { "full_vivado_build" })
    artifacts = $hashes
    active_source_sha256 = $sourceHashes
    host_tool_sha256 = $hostToolHashes
    test_sha256 = $testHashes
}
$manifestPath = Join-Path $output "artifact_manifest.json"
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding utf8
Write-Host "BUILD_DONE bitstream=$($hashes['zcu106_adc_capture.bit']) manifest=$manifestPath"
