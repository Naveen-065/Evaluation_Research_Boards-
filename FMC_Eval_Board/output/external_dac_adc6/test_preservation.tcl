# Exercise the real host procedure against a DAC register model.
set scenario [lindex $argv 0]
set regs [dict create 0x01 0x0A70 0x02 0]
foreach a {0x03 0x04 0x05 0x06 0x07 0x08 0x09 0x0A 0x0B 0x0C 0x0D 0x10 0x11 0x12 0x13 0x14 0x15 0x16 0x17 0x18 0x19 0x1A 0x1B 0x1C 0x1D 0x1E 0x1F} {
    dict set regs $a [expr {($a * 123) & 65535}]
}
dict set regs 0x03 0x0004
dict set regs 0x04 0x7F00
dict set regs 0x09 0x4110
dict set regs 0x0A 0x0100
dict set regs 0x0B 0x0101
if {$scenario eq "powerup"} {dict set regs 0x03 0x0AA4; dict set regs 0x09 0xFFFF}
if {$scenario eq "no_sdo"} {dict set regs 0x01 0xFFFF}
set original $regs
set writes {}
proc rd {a} {global regs; return [dict get $regs $a]}
proc wr {a value} {global regs writes; lappend writes [list $a $value]; dict set regs $a $value}
proc close_spi {} {
    global regs original scenario
    dict for {a old} $original {
        set value [dict get $regs $a]
        set allowed 0
        switch -- $a {
            0x03 {set allowed 0x20}
            0x06 - 0x09 {set allowed 0x4100}
            0x07 {set allowed 0x3003}
            0x0A {set allowed 0x0F00}
            0x0B {set allowed 0x000F}
            0x18 - 0x1E {set allowed 0xFFFF}
        }
        if {(($old ^ $value) & (~$allowed & 0xFFFF)) != 0} {error "Unrelated register bits changed: $a"}
    }
    if {[dict get $regs 0x18] != 0x599A || [dict get $regs 0x1E] != 0x4000 || ([dict get $regs 0x09] & 0x4100)} {error "Spare output configuration wrong"}
    puts "PRESERVE_OTHER_DAC_CHANNELS_TEST_PASS scenario=$scenario"
}
rename source original_source
proc source {args} {
    set p [lindex $args end]
    if {[file tail $p] eq "spi_host.tcl"} {return}
    uplevel 1 [linsert $args 0 original_source]
}
if {[catch {source [file join [file dirname [info script]] enable_spares_preserve.tcl]} e]} {
    if {$scenario eq "no_sdo" && [llength $writes] == 0 && [string match {*readback not verified*} $e]} {
        puts "MISSING_SDO_ZERO_WRITES_TEST_PASS"
        exit 0
    }
    error $e
}
