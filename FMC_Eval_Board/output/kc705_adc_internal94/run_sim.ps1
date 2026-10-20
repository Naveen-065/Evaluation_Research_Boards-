$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$iverilog = Get-Command iverilog -ErrorAction Stop
$vvp = Get-Command vvp -ErrorAction Stop
& $iverilog.Source -g2012 -s tb_ads5282_control -o (Join-Path $here 'tb_ads5282_control.vvp') `
    (Join-Path $here 'kc705_adc_test.v') (Join-Path $here 'tb_ads5282_control.v')
if ($LASTEXITCODE -ne 0) { throw 'iverilog compilation failed' }
& $vvp.Source (Join-Path $here 'tb_ads5282_control.vvp')
if ($LASTEXITCODE -ne 0) { throw 'simulation failed' }
& $iverilog.Source -g2012 -s tb_dac81416_shunt_control -o (Join-Path $here 'tb_dac81416_shunt_control.vvp') `
    (Join-Path $here 'kc705_adc_test.v') (Join-Path $here 'tb_dac81416_shunt_control.v')
if ($LASTEXITCODE -ne 0) { throw 'DAC iverilog compilation failed' }
& $vvp.Source (Join-Path $here 'tb_dac81416_shunt_control.vvp')
if ($LASTEXITCODE -ne 0) { throw 'DAC simulation failed' }
