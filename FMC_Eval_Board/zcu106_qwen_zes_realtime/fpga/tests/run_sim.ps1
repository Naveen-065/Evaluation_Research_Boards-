param(
    [string]$VivadoRoot = "C:\Xilinx\Vivado\2022.2"
)

$ErrorActionPreference = "Stop"
$fpgaRoot = Split-Path -Parent $PSScriptRoot
$work = Join-Path $fpgaRoot ("output\sim\run_" + [Guid]::NewGuid().ToString("N"))
# Each run gets a fresh ignored subdirectory. XSim can leave a partially linked
# snapshot locked after an interrupted run; reusing it produces misleading
# missing-object linker errors and deleting it immediately can fail on Windows.
New-Item -ItemType Directory -Force -Path $work | Out-Null

$xvlog = Join-Path $VivadoRoot "bin\xvlog.bat"
$xelab = Join-Path $VivadoRoot "bin\xelab.bat"
$xsim = Join-Path $VivadoRoot "bin\xsim.bat"
foreach ($tool in @($xvlog, $xelab, $xsim)) {
    if (-not (Test-Path -LiteralPath $tool)) {
        throw "Vivado simulator tool not found: $tool"
    }
}

function Invoke-SimulationAndRequirePass {
    param(
        [string]$Snapshot,
        [string]$PassMarker,
        [string]$Label
    )
    # XSim 2022.2 may return process exit code zero after a Verilog $fatal.
    # Preserve its transcript and require the testbench's exact PASS marker so
    # CI cannot silently accept an early/fatal simulation termination.
    $lines = @(& $xsim $Snapshot -runall 2>&1)
    $simExitCode = $LASTEXITCODE
    $lines | ForEach-Object { Write-Host $_ }
    $transcript = $lines -join [Environment]::NewLine
    if ($simExitCode -ne 0) {
        throw "$Label xsim failed with exit code $simExitCode"
    }
    if ($transcript -match '(?m)^Fatal:' -or
        -not $transcript.Contains($PassMarker)) {
        throw "$Label simulation did not reach its required PASS marker"
    }
}

Push-Location $work
try {
    & $xvlog `
        (Join-Path $fpgaRoot "kc705_cell_control\cell_control_engine.v") `
        (Join-Path $fpgaRoot "kc705_cell_control\cell_control_ramp_wrapper.v") `
        (Join-Path $fpgaRoot "kc705_cell_control\runtime_dac_spi.v") `
        (Join-Path $fpgaRoot "kc705_cell_control\uart_rx_8n1.v") `
        (Join-Path $fpgaRoot "tests\tb_bitmap_scheduler.v") `
        (Join-Path $fpgaRoot "baseline\tb_control.v")
    if ($LASTEXITCODE -ne 0) { throw "xvlog failed with exit code $LASTEXITCODE" }

    & $xelab tb_bitmap_scheduler -s tb_bitmap_scheduler_sim --debug typical
    if ($LASTEXITCODE -ne 0) { throw "xelab failed with exit code $LASTEXITCODE" }

    Invoke-SimulationAndRequirePass `
        -Snapshot "tb_bitmap_scheduler_sim" `
        -PassMarker "PASS disabled-interlock BMP2/op4/direct-WR_WAIT-abort, bitmap load/readback, fail-closed launch, two-phase SET-then-RESET scheduler, per-cell interlock recovery, full patterns/abort, page boundary, packet reset cadence, op12/13 compatibility" `
        -Label "bitmap"

    & $xelab tb_control -s tb_control_regression --debug typical
    if ($LASTEXITCODE -ne 0) { throw "legacy xelab failed with exit code $LASTEXITCODE" }

    Invoke-SimulationAndRequirePass `
        -Snapshot "tb_control_regression" `
        -PassMarker "PASS protected DAC and WB supply mask, serial scan, FPGA MAC, ADC trace, WB frame/UART, abort/fault" `
        -Label "legacy"
}
finally {
    Pop-Location
}
