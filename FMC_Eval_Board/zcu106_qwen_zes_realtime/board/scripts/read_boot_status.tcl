connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "PSU"}
puts "BOOT_MODE_USER"
puts [mrd 0xFF5E0200]
puts "FSBL_ERROR_STATUS"
puts [mrd 0xFFD80060]
puts "PMU_GLOBAL_PWR_STATE"
puts [mrd 0xFFD80100]
puts "CSU_BOOTROM_ERROR"
puts [mrd 0xFFD80528]
puts "PMU_GLOBAL_ERROR_STATUS_1"
puts [mrd 0xFFD80530]
puts "SD1_PRESENT_STATE"
puts [mrd 0xFF170024]
disconnect
exit
