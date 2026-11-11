# One explicitly invoked nonvolatile store of the reviewed U55 configuration.
# TI SLUU337 section7.4: STORE_DEFAULT_ALL saves Operating Memory to Default
# Store; OPERATION and PHASE_ENABLE are not saved. No restore/reset is issued.
# Power-cycle persistence remains unverified until a later physical power cycle.
set here [file dirname [file normalize [info script]]]
proc store_read_file {path} {
    set channel [open $path r]
    set data [read $channel]
    close $channel
    return $data
}
set baseline [store_read_file [file join $here controller_before.txt]]
set changed [store_read_file [file join $here change_1p8.txt]]
if {![regexp -line {^DEVICE_ID_FIRST_BYTES=30 85 67 68 57 50 52 56\r?$} $baseline]} {
    error "Reviewed baseline does not identify UCD9248"
}
if {![regexp -line {^U55_ADDRESS=0x34\r?$} $baseline] ||
    ![regexp -line {^PHASE_INFO=4 1 4 16 64\r?$} $baseline]} {
    error "Reviewed baseline address/phase mapping mismatch"
}
set marker VADJ_VOLATILE_CHANGE_OK_NOT_STORED_TO_FLASH
if {[lindex [split [string trim $changed] "\n"] end] ne $marker ||
    [regexp -all -line "^${marker}\\r?\$" $changed] != 1} {
    error "Voltage-change log is incomplete or has ambiguous completion markers"
}
array set original {}
foreach line [split $baseline "\n"] {
    if {[regexp {^PAGE=([0-3]) (BYTE|WORD) (0x[0-9a-f]+)=(0x[0-9a-f]+)\r?$} $line -> pg kind reg val]} {
        set key "$pg,[expr {$reg}]"
        if {[info exists original($key)]} {error "Duplicate baseline register $key"}
        set original($key) [list $kind [expr {$val}]]
    }
}
if {[array size original] != 136} {error "Expected exactly136 unique baseline registers"}
set byte_settings {1 2 32 65 69}
set word_settings {33 35 36 37 38 39 41 42 64 66 67 68 72 94 95 96 97 98 100 101 102}
array set expected {}
foreach line [split $changed "\n"] {
    if {[string match "VERIFIED*" $line]} {
        if {![regexp {^VERIFIED PAGE=([0-3]) (BYTE|WORD) (0x[0-9a-f]+)=(0x[0-9a-f]+)\r?$} $line -> pg kind reg val]} {
            error "Malformed VERIFIED setting in voltage-change log"
        }
        set reg [expr {$reg}]
        set val [expr {$val}]
        set key "$pg,$reg"
        if {[info exists expected($key)]} {error "Duplicate VERIFIED setting $key"}
        if {($kind eq "BYTE" && ($reg ni $byte_settings || $val > 255)) ||
            ($kind eq "WORD" && ($reg ni $word_settings || $val > 65535))} {
            error "Unexpected VERIFIED register type/range $key"
        }
        if {![info exists original($key)] || [lindex $original($key) 0] ne $kind} {
            error "VERIFIED setting lacks matching baseline register $key"
        }
        if {($pg != 3 || $reg ni {33 37 38 64 66 67 68 72 94 95}) &&
            $val != [lindex $original($key) 1]} {
            error "Unexpected change outside the reviewed VADJ settings $key"
        }
        set expected($key) [list $kind $val]
    }
}
if {[array size expected] != 104} {error "Expected exactly104 unique VERIFIED settings"}
foreach pg {0 1 2 3} {
    foreach reg [concat $byte_settings $word_settings] {
        if {![info exists expected($pg,$reg)]} {error "Missing VERIFIED setting $pg,$reg"}
    }
    if {[lindex $expected($pg,32) 1] != 0x14} {error "Expected LINEAR16 exponent-12 on every rail"}
}
if {[lindex $expected(3,33) 1] != 0x1ccd || [lindex $expected(3,1) 1] ni {0 64 128}} {
    error "Reviewed PAGE3 is not the intended normal1.8V configuration"
}

# Reserve an exclusive attempt log before hardware access or the store command.
# A failure or ambiguous outcome leaves this file in place to block blind retries.
set log [open [file join $here store_1p8.txt] {WRONLY CREAT EXCL}]
proc store_record {line} {
    global log
    puts $line
    puts $log $line
    flush $log
}
proc store_rb_pec {reg} {
    set bytes [transfer [list $reg] 2]
    set wanted [crc8 [list 0x68 $reg 0x69 [lindex $bytes 0]]]
    if {[lindex $bytes 1] != $wanted} {error "Read-byte PEC mismatch at register $reg"}
    return [lindex $bytes 0]
}
proc store_phase_check {} {
    set bytes [transfer {210} 6]
    set mapping [lrange $bytes 0 4]
    if {$mapping ne {4 1 4 16 64}} {error "Live U55 phase mapping mismatch"}
    if {[lindex $bytes 5] != [crc8 [concat {0x68 0xd2 0x69} $mapping]]} {
        error "Live phase mapping PEC mismatch"
    }
}
proc store_check_all {stage} {
    global expected byte_settings word_settings
    store_phase_check
    foreach pg {0 1 2 3} {
        page $pg
        foreach reg [concat $byte_settings $word_settings] {
            lassign $expected($pg,$reg) kind wanted
            if {$kind eq "BYTE"} {set got [store_rb_pec $reg]} else {set got [rw_pec $reg]}
            if {$got != $wanted} {error "$stage setting mismatch PAGE=$pg register=$reg wanted=$wanted got=$got"}
            store_record [format "%s VERIFIED PAGE=%d %s 0x%02x=0x%04x" $stage $pg $kind $reg $got]
        }
        set volts [expr {[rw_pec 0x8b]/4096.0}]
        set nominal [expr {[lindex $expected($pg,33) 1]/4096.0}]
        if {$nominal <= 0 || abs($volts-$nominal) > 0.03*$nominal} {
            error "$stage rail telemetry outside3percent PAGE=$pg volts=$volts expected=$nominal"
        }
        set word [rw_pec 0x79]
        if {$word != 0} {error "$stage nonzero STATUS_WORD PAGE=$pg value=$word"}
        foreach reg {0x7a 0x7b 0x7c 0x7d 0x7e 0x80} {
            set value [store_rb_pec $reg]
            if {$value != 0} {error "$stage nonzero status PAGE=$pg register=$reg value=$value"}
        }
        store_record [format "%s HEALTHY PAGE=%d VOLTS=%.6f STATUS_WORD=0x0000 STATUS_BYTES=0" $stage $pg $volts]
    }
}
proc store_main {} {
    global here
    store_record "BEGIN_SINGLE_STORE_DEFAULT_ALL_ATTEMPT"
    store_record "IDENTITY_FROM_REVIEWED_BASELINE=UCD9248 ADDRESS=0x34"
    uplevel #0 [list source [file join $here pmbus_host.tcl]]
    store_check_all PRE_STORE
    page 3
    if {[store_rb_pec 0] != 3 || [store_rb_pec 0x20] != 0x14 || [rw_pec 0x21] != 0x1ccd} {
        error "Final VADJ guard failed before STORE_DEFAULT_ALL"
    }
    set pec [crc8 {0x68 0x11}]
    store_record [format "STORE_COMMAND_ABOUT_TO_SEND ADDRESS=0x34 COMMAND=0x11 PEC=0x%02x" $pec]
    # Exactly one send-byte-with-PEC transaction; never retry this command.
    transfer [list 0x11 $pec] 0
    store_record "STORE_COMMAND_ACKNOWLEDGED FLASH_CONTENTS_NOT_DIRECTLY_VERIFIED"
    # Keep the bus quiet while the controller performs its flash operation.
    after 2000
    store_check_all POST_STORE
    page 3
    store_record "STORE_COMMAND_ACK_AND_POSTCHECK_OK"
    store_record "POWER_CYCLE_PERSISTENCE_NOT_YET_VERIFIED"
}
set store_code [catch {store_main} store_result store_options]
if {$store_code} {catch {store_record "STORE_ATTEMPT_FAILED_OR_UNCERTAIN: $store_result; DO_NOT_RETRY_AUTOMATICALLY"}}
catch {close_bridge}
close $log
if {$store_code} {return -options $store_options $store_result}
