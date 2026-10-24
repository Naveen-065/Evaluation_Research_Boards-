connect -url tcp:127.0.0.1:3121
puts "XSCT_TARGETS_BEGIN"
puts [targets]
puts "XSCT_TARGETS_END"
puts "XSCT_JTAG_BEGIN"
puts [jtag targets]
puts "XSCT_JTAG_END"
disconnect
exit
