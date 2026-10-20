# Catalog/help only: no FPGA programming or flash access.
foreach cmd {create_hw_cfgmem create_hw_bitstream readback_hw_cfgmem program_hw_cfgmem write_cfgmem boot_hw_device} {
    help $cmd
}
foreach pattern {*n25q128* *mt25ql128*} {
    foreach part [get_cfgmem_parts -quiet $pattern] {
        puts "CFGMEM_CANDIDATE $part"
        report_property $part
    }
}
exit
