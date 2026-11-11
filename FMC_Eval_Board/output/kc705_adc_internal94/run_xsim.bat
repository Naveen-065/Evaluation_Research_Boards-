@echo off
setlocal
cd /d "%~dp0"
call C:\AMDDesignTools2\2026.1\Vivado\bin\xvlog.bat -sv kc705_adc_test.v tb_ads5282_control.v tb_dac81416_shunt_control.v
if errorlevel 1 exit /b 1
call C:\AMDDesignTools2\2026.1\Vivado\bin\xelab.bat tb_ads5282_control -s tb_ads5282_control_sim
if errorlevel 1 exit /b 1
call C:\AMDDesignTools2\2026.1\Vivado\bin\xsim.bat tb_ads5282_control_sim -runall
if errorlevel 1 exit /b 1
call C:\AMDDesignTools2\2026.1\Vivado\bin\xelab.bat tb_dac81416_shunt_control -s tb_dac81416_shunt_control_sim
if errorlevel 1 exit /b 1
call C:\AMDDesignTools2\2026.1\Vivado\bin\xsim.bat tb_dac81416_shunt_control_sim -runall
if errorlevel 1 exit /b 1
endlocal
