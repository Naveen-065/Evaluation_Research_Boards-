# Boot the ZCU106 from its on-board SD card for the current power cycle while
# the physical boot-mode switches remain in JTAG mode. The ZCU106 card slot is
# wired to PS SD1 (MIO 39..51) through a voltage-level translator, so it must
# use the Zynq UltraScale+ SD1_LS boot-mode value 0xE.
# BOOT_MODE_USER is POR-only reset, so USE_ALT survives the system reset below.
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "PSU"}

set boot_mode_address 0xFF5E0200
set current [lindex [mrd -value $boot_mode_address] 0]
set current_mode [expr {$current & 0xF}]
set current_use_alt [expr {($current >> 8) & 1}]
set current_alt [expr {($current >> 12) & 0xF}]

# Accept physical JTAG mode or either earlier SD diagnostic selection. Refuse
# to replace any unrelated selection silently.
if {!($current_mode == 0 || ($current_use_alt == 1 && ($current_alt == 3 || $current_alt == 5 || $current_alt == 14)))} {
    error [format "Refusing alternate boot override: expected JTAG or an SD diagnostic mode, read 0x%08X" $current]
}

# ALT_BOOT_MODE[15:12]=0xE (SD1_LS), USE_ALT[8]=1. The read-only BOOT_MODE
# field must report 0xE before reset is issued.
mwr $boot_mode_address 0x0000E100
set updated [lindex [mrd -value $boot_mode_address] 0]
if {($updated & 0xF) != 14 || (($updated >> 8) & 1) != 1 || (($updated >> 12) & 0xF) != 14} {
    error [format "SD1_LS alternate boot selection did not latch: 0x%08X" $updated]
}
puts [format "SD1_LS_ALT_BOOT_LATCHED 0x%08X" $updated]
rst -system
puts "SYSTEM_RESET_ISSUED"
disconnect
exit
