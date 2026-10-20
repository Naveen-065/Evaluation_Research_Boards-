# Read-modify-write only external DAC8/DAC14. Requires SDO -> AX7020 J10-32.
set here [file dirname [file normalize [info script]]]
source [file join $here spi_host.tcl]
for {set i 0} {$i < 3} {incr i} {
    set id [rd 0x01]
    puts "DAC_DEVICE_ID=[format %04X $id]"
    if {($id >> 2) != 0x29C} {error "DAC81416 readback not verified. Check SDO wiring. No DAC registers were changed."}
}
set addresses {0x03 0x04 0x05 0x06 0x07 0x08 0x09 0x0A 0x0B 0x0C 0x0D 0x10 0x11 0x12 0x13 0x14 0x15 0x16 0x17 0x18 0x19 0x1A 0x1B 0x1C 0x1D 0x1E 0x1F}
set before [dict create]
foreach a $addresses {dict set before $a [rd $a]}
# Require stable readback before touching shared registers.
foreach a $addresses {
    if {[rd $a] != [dict get $before $a]} {error "Unstable DAC readback at $a; no writes performed"}
}
file mkdir [file join $here evidence]
set stamp [clock format [clock seconds] -format %Y%m%d_%H%M%S]
set f [open [file join $here evidence "dac_before_${stamp}.txt"] w]
dict for {a val} $before {puts $f "[format %02X $a]=[format %04X $val]"}
close $f
set cfg [dict get $before 0x03]
set gen [dict get $before 0x04]
set oldmask [dict get $before 0x09]
if {$cfg & 0x1A} {error "Nonstandard CRC/stream/SDO timing mode; no writes performed"}
if {$gen & 0x90} {error "DAC8/9 or DAC14/15 differential mode enabled; independent spare changes would affect another channel"}
if {($cfg & 0x20) && (($oldmask | 0x4100) != 0xFFFF)} {
    error "Device globally powered down with other channels armed. Enabling the device would also activate them; no writes performed."
}
set expected $before
dict set expected 0x03 [expr {$cfg & ~0x20}]
dict set expected 0x06 [expr {[dict get $before 0x06] & ~0x4100}]
dict set expected 0x07 [expr {[dict get $before 0x07] & ~0x3003}]
dict set expected 0x09 [expr {$oldmask & ~0x4100}]
dict set expected 0x0A [expr {[dict get $before 0x0A] & ~0x0F00}]
dict set expected 0x0B [expr {[dict get $before 0x0B] & ~0x000F}]
dict set expected 0x18 0x599A
dict set expected 0x1E 0x4000
set alarm [rd 0x02]
if {$alarm & 5} {error "DAC temperature/CRC alarm active; no writes performed"}
# Power down only the two requested spare outputs while updating their ranges.
wr 0x09 [expr {$oldmask | 0x4100}]
foreach a {0x06 0x07 0x0A 0x0B 0x18 0x1E} {
    set val [dict get $expected $a]
    if {$val != [dict get $before $a]} {wr $a $val}
}
# Verify target data/ranges and every untouched register before enabling.
foreach a $addresses {
    set wanted [dict get $expected $a]
    if {$a eq "0x09"} {set wanted [expr {$oldmask | 0x4100}]}
    if {$a eq "0x03"} {set wanted $cfg}
    if {[rd $a] != $wanted} {error "Readback mismatch at $a; spare channels remain powered down"}
}
if {[dict get $expected 0x03] != $cfg} {wr 0x03 [dict get $expected 0x03]}
wr 0x09 [dict get $expected 0x09]
set f [open [file join $here evidence "dac_after_${stamp}.txt"] w]
foreach a $addresses {
    set actual [rd $a]
    puts $f "[format %02X $a]=[format %04X $actual]"
    if {$actual != [dict get $expected $a]} {
        close $f
        wr 0x09 [expr {$oldmask | 0x4100}]
        error "Final readback mismatch at $a; spare channels powered down"
    }
}
close $f
puts "EXTERNAL_DAC8_DAC14_PROGRAMMED_AND_READBACK_VERIFIED"
puts "DAC8=1.75 V target (0x599A on 0..5 V); DAC14=1.25 V target (0x4000 on 0..5 V)."
puts "Other DAC data, range nibbles and power bits preserved; reference configuration unchanged."
puts "Verify actual analog voltages with a meter before connecting to PCB J7 pins 1 and 2."
close_spi
exit
