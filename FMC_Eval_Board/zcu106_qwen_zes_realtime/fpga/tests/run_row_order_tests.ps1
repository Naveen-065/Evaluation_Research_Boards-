param(
    [string]$VivadoRoot = "C:\Xilinx\Vivado\2022.2"
)

$ErrorActionPreference = "Stop"
$fpgaRoot = Split-Path -Parent $PSScriptRoot
$vivado = Join-Path $VivadoRoot "bin\vivado.bat"
$testScript = Join-Path $PSScriptRoot "test_row_order_common.tcl"
$mockScript = Join-Path $PSScriptRoot "mock_row_order_read.tcl"
$work = Join-Path $fpgaRoot "output\row_order_test"

if (-not (Test-Path -LiteralPath $vivado)) {
    throw "Vivado not found: $vivado"
}

New-Item -ItemType Directory -Force -Path $work | Out-Null
Push-Location $work
try {
    foreach ($case in @(
        @($testScript, "PASS row-order parser, bounds, and deterministic permutations", "parser"),
        @($mockScript, "PASS row-order read-only mock integration, failure cleanup, and atomic outputs", "mock integration")
    )) {
        $lines = @(& $vivado -mode batch -nojournal -nolog -notrace -source $case[0] 2>&1)
        $exitCode = $LASTEXITCODE
        $lines | ForEach-Object { Write-Host $_ }
        $transcript = $lines -join [Environment]::NewLine
        if ($exitCode -ne 0) {
            throw "row-order $($case[2]) tests failed with exit code $exitCode"
        }
        if (-not $transcript.Contains($case[1])) {
            throw "row-order $($case[2]) tests did not reach their required PASS marker"
        }
    }

    $jsonPath = Join-Path $work "mock_reverse.json"
    $csvPath = Join-Path $work "mock_reverse.csv"
    $document = Get-Content -Raw -LiteralPath $jsonPath | ConvertFrom-Json
    $records = @(Import-Csv -LiteralPath $csvPath)
    if ($document.protocol -ne "ZCU106_ROW_ORDER_READ_V1" -or
        $document.cells.Count -ne 32 -or $records.Count -ne 32) {
        throw "row-order mock outputs failed JSON/CSV structural validation"
    }
}
finally {
    Pop-Location
}
