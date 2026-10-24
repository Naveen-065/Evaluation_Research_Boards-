set here [file dirname [file normalize [info script]]]
source [file join $here .. tools bitmap_handshake.tcl]

proc assert_equal {actual expected message} {
 if {$actual!=$expected} {
  error "$message: expected $expected, got $actual"
 }
}

set toggle 1
set tagged_ready [expr {($toggle<<15)|(1<<9)}]
set tagged_busy [expr {($toggle<<15)|(1<<8)}]
set tagged_fault [expr {$tagged_ready|(1<<10)}]
set bpr2 [expr {0x42505232<<224}]
set bpd2 [expr {0x42504432<<224}]
# Exact invalid sample captured on ZCU106 on 2026-10-24: result0 said READY,
# while result1 was a torn word rather than either legal bitmap signature.
set torn [expr 0x5042423203815000000000000000000000000000000000000000000000000000]

assert_equal [bitmap_response_complete 15 $toggle $tagged_busy $bpr2] 0 \
 "busy BPR2 response was accepted"
assert_equal [bitmap_response_complete 15 $toggle $tagged_ready $bpr2] 0 \
 "progress BPR2 response was accepted as completion"
assert_equal [bitmap_response_complete 15 $toggle $tagged_ready $torn] 0 \
 "captured torn response was accepted as completion"
assert_equal [bitmap_response_complete 15 $toggle $tagged_ready $bpd2] 1 \
 "valid BPD2 response was rejected"
assert_equal [bitmap_response_complete 15 $toggle $tagged_fault 0] 1 \
 "tagged fault response was not returned to the caller"
assert_equal [bitmap_response_complete 15 0 $tagged_ready $bpd2] 0 \
 "wrong-tag BPD2 response was accepted"
assert_equal [bitmap_response_complete 14 $toggle $tagged_ready 0] 1 \
 "ordinary ready response was rejected"

puts "PASS bitmap completion predicate rejects BPR2/torn/wrong-tag frames and accepts tagged BPD2"
