"""Generate board-specific integration from the verified ADC receiver."""
from pathlib import Path
import re
HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'kc705_adc_capture'
s=(BASE/'kc705_adc_test.v').read_text()
s=s.replace('input wire scan_si,','inout wire scan_si,').replace('input wire reset_b,','inout wire reset_b,')
s=s.replace('// DAC2 is VCC_SET; DAC6/7/8 are unused. DAC14 stays off because VDDA1\n    // is supplied by +3V3 through NT12. DAC15 supplies nominal 1.8 V VCCD2.', '// DAC2 is VCC_SET. NT12 removed; NT22 routes DAC14=3.0 V to VDDA1.\n    // DAC15 remains 1.8 V. All user analog rails follow supply startup.')
s=s.replace('OBUF scan_se_output      (.I(1\'b0)', 'OBUF scan_se_output      (.I(scan_se_drive)')
s=s.replace('OBUF scan_tm_output      (.I(1\'b0)', 'OBUF scan_tm_output      (.I(scan_tm_drive)')
s=s.replace('OBUF fpga_loe_output     (.I(1\'b0)', 'OBUF fpga_loe_output     (.I(scan_interface_enable)')
block='''
    wire [63:0] scan_command;
    (* DONT_TOUCH="TRUE" *) wire [255:0] scan_result0, scan_result1;
    wire scan_interface_enable, scan_reset_low, scan_tm_drive, scan_se_drive, scan_si_drive;
    wire scan_si_read, scan_reset_read;
    scan_read_vio u_scan_vio (.clk(sysclk), .probe_out0(scan_command),
        .probe_in0(scan_result0), .probe_in1(scan_result1));
    scan_read_engine scan_reader (
        .clk(sysclk), .feedback_clk(si5351_clk1_1v8), .ready_i(ready_i), .reset_i(scan_reset_read),
        .dac_ready(dac_enable && dac_ready),
        .adc_healthy(run_enable && config_done && ret_lclk_60m && ret_adclk_10m && frame_locked_sync[1]),
        .command(scan_command), .sample_valid(snapshot_valid), .samples(snapshot_words),
        .interface_enable(scan_interface_enable), .reset_low(scan_reset_low),
        .tm(scan_tm_drive), .se(scan_se_drive), .si(scan_si_drive),
        .result0(scan_result0), .result1(scan_result1));
    IOBUF scan_si_buffer (.I(scan_si_drive), .T(!scan_interface_enable), .O(scan_si_read), .IO(scan_si));
    // Open-drain reset: never actively drive high against FT232H or SW1.
    IOBUF scan_reset_buffer (.I(1'b0), .T(!(scan_interface_enable && scan_reset_low)),
        .O(scan_reset_read), .IO(reset_b));
'''
s=s.replace('    // Preserve all reviewed non-ADC quiescent outputs from the static image.',block+'\n    // Existing ADC/DAC pin routing and voltage standards are preserved.')
s=s.replace('si5351_clk1_1v8, scan_si, reset_b, ready_i', 'si5351_clk1_1v8, scan_si_read, scan_reset_read, ready_i')
# Insert DAC14 code before the supply-enable frame, shifting later indices.
start=s.index('    function [23:0] frame_for_index;')
end=s.index('    endfunction',start)
part=s[start:end]
part=re.sub(r"5'd(\d+):", lambda m: f"5'd{int(m[1])+1}:" if int(m[1])>=9 else m[0],part)
part=part.replace("5'd10: frame_for_index = 24'h097FDF;", "5'd9: frame_for_index = 24'h1E999A;       // DAC14 VDDA1 = 3.0 V via NT22\n                5'd10: frame_for_index = 24'h093FDF;")
part=part.replace('supply channels 15,5 first','supply channels 15,14,5 first')
part=part.replace("24'h0941D0", "24'h0901D0").replace('off: 4,6,7,8,14','off: 4,6,7,8')
s=s[:start]+part+s[end:]
s=s.replace("frame_index == 5'd9", "frame_index == 5'd10").replace("frame_index == 5'd20", "frame_index == 5'd21")
(HERE/'kc705_adc_test.v').write_text(s)
x=(BASE/'kc705_adc_test.xdc').read_text()
x+='\n# Scan data and open-drain reset become bidirectional; original pins/IOSTANDARD unchanged.\nset_property DRIVE 4 [get_ports {scan_si reset_b}]\nset_property SLEW SLOW [get_ports {scan_si reset_b}]\nset_false_path -to [get_cells -hier -filter {NAME =~ scan_reader/*_sync_reg[0]}]\n'
(HERE/'kc705_adc_test.xdc').write_text(x)
b=(BASE/'build_bringup.tcl').read_text().replace('create_project -force kc705_adc_capture','create_project -force kc705_scan_read')
b=b.replace('add_files [list', '''create_ip -name vio -vendor xilinx.com -library ip -module_name scan_read_vio
set_property -dict [list CONFIG.C_NUM_PROBE_IN 2 CONFIG.C_NUM_PROBE_OUT 1 CONFIG.C_PROBE_IN0_WIDTH 256 CONFIG.C_PROBE_IN1_WIDTH 256 CONFIG.C_PROBE_OUT0_WIDTH 64 CONFIG.C_PROBE_OUT0_INIT_VAL 0x0000000000000000] [get_ips scan_read_vio]
generate_target all [get_ips scan_read_vio]
create_ip_run [get_ips scan_read_vio]
launch_runs scan_read_vio_synth_1 -jobs 4
wait_on_run scan_read_vio_synth_1
add_files [file join $here scan_read_engine.v]
add_files [list''')
(HERE/'build_bringup.tcl').write_text(b)
# CLK0/1 900 MHz /450 = 2 MHz; ADC remains separately clocked at 10 MSPS.
clock=(BASE/'program_si5351_10mhz.tcl').read_text().replace('0x2B','0xDF').replace('10mhz','2mhz').replace('10MHZ','2MHZ').replace('10000000','2000000').replace('/90','/450').replace('10 MHz','2 MHz')
(HERE/'program_si5351_2mhz.tcl').write_text(clock)
(HERE/'assert_clock.tcl').write_text((BASE/'assert_clock.tcl').read_text().replace('0x2B','0xDF').replace('10MHZ','2MHZ'))
for name in ['enable_dac_scan.tcl','enable_adc_10m.tcl']:
    t=(BASE/name).read_text().replace('dac_frame_index] == 20','dac_frame_index] == 21').replace('dac_frame_index] != 20','dac_frame_index] != 21').replace('dac_frame_index 20','dac_frame_index 21')
    t=t.replace('DAC13=1.0 DAC15','DAC13=1.0 DAC14=3.0 DAC15').replace('DAC8 DAC14; mask=0x41D0','DAC8; mask=0x01D0')
    (HERE/name).write_text(t)
# Minimal scan-only firmware; no user Wishbone writes or programming operation.
fw=['#include <defs.h>','#include <stub.h>','void main(void) {','reg_gpio_mode1=1; reg_gpio_mode0=0; reg_gpio_ien=1; reg_gpio_oe=1; reg_gpio_out=0;','reg_mprj_datal=0; reg_mprj_datah=0;']
for i in range(38):
    mode='GPIO_MODE_USER_STD_INPUT_NOPULL'
    if i==0: mode='GPIO_MODE_MGMT_STD_ANALOG'
    if i==1: mode='GPIO_MODE_MGMT_STD_OUTPUT'
    if i in [2,3,4,5,6]: mode='GPIO_MODE_MGMT_STD_INPUT_NOPULL'
    if 25<=i<=34: mode='GPIO_MODE_USER_STD_ANALOG'
    fw.append(f'reg_mprj_io_{i}={mode};')
fw+=['reg_mprj_xfer=1; while(reg_mprj_xfer==1) {}','reg_mprj_datal=2; /* GPIO1 READY only after all pad routes are applied. */','reg_gpio_out=1;','while(1) {}','}']
(HERE/'firmware/scan_read.c').write_text('\n'.join(fw)+'\n')
print('Generated scan integration: NT22/DAC14=3.0 V, OP_SET=0, independent ADC 10 MSPS.')
