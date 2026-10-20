set rc 0
puts "CODEX_JTAG_SCAN_BEGIN"
if {[catch {
    open_hw_manager
    connect_hw_server -allow_non_jtag
    set targets [get_hw_targets]
    puts "TARGET_COUNT=[llength $targets]"
    foreach target $targets {
        puts "TARGET=$target"
        current_hw_target $target
        if {[catch {open_hw_target} open_error]} {
            puts "TARGET_OPEN_ERROR=$open_error"
            continue
        }
        set devices [get_hw_devices]
        puts "DEVICE_COUNT=[llength $devices]"
        foreach device $devices {
            current_hw_device $device
            set part ""
            set idcode ""
            set dna ""
            catch {set part [get_property PART $device]}
            catch {set idcode [get_property IDCODE $device]}
            catch {set dna [get_property REGISTER.EFUSE.FUSE_DNA $device]}
            puts "DEVICE=$device PART=$part IDCODE=$idcode DNA=$dna"
        }
        close_hw_target
    }
} scan_error]} {
    puts "SCAN_FATAL=$scan_error"
    set rc 1
}
catch {disconnect_hw_server}
catch {close_hw_manager}
puts "CODEX_JTAG_SCAN_END RC=$rc"
exit $rc
