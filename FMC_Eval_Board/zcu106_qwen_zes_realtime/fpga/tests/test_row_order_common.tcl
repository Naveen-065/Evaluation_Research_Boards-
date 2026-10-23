set here [file dirname [file normalize [info script]]]
source [file join $here .. tools row_order_common.tcl]

proc assert_equal {actual expected label} {
 if {$actual ne $expected} {
  error "$label: expected '$expected', got '$actual'"
 }
}

proc assert_error {script pattern label} {
 if {![catch {uplevel 1 $script} message]} {
  error "$label: expected an error"
 }
 if {![string match $pattern $message]} {
  error "$label: error '$message' does not match '$pattern'"
 }
}

assert_equal [row_order::parse_rows "0,3,7-9"] {0 3 7 8 9} "row parsing"
assert_equal [row_order::parse_rows "08,09-10"] {8 9 10} "decimal leading zeros"
assert_equal [row_order::parse_rows "31"] {31} "last physical row"
assert_error {row_order::parse_rows {}} {*must not be empty*} "empty rows"
assert_error {row_order::parse_rows "2,2"} {*more than once*} "duplicate row"
assert_error {row_order::parse_rows "4-2"} {*must be ascending*} "descending range"
assert_error {row_order::parse_rows "32"} {*outside*} "out-of-range row"
assert_error {row_order::parse_rows "1,x"} {*invalid row token*} "malformed row"

set ascending {}
for {set column 0} {$column<32} {incr column} { lappend ascending $column }
assert_equal [row_order::columns forward {}] $ascending "forward columns"
assert_equal [row_order::columns reverse {}] [lreverse $ascending] "reverse columns"

set random_a [row_order::columns random 12345]
set random_b [row_order::columns random 12345]
set random_c [row_order::columns random 12346]
assert_equal $random_a $random_b "seed reproducibility"
if {$random_a eq $random_c} { error "different random seeds produced the same permutation" }
assert_equal [lsort -integer $random_a] $ascending "random result is a permutation"
assert_error {row_order::columns random 0} {*1..2147483647*} "zero seed"
assert_error {row_order::columns diagonal {}} {*forward, reverse, or random*} "invalid order"
assert_error {row_order::validate_order_and_seed forward 7} {*only when order is random*} "unused seed"
assert_equal [row_order::validate_order_and_seed RANDOM 99] {random 99} "normalization"
assert_equal [row_order::validate_order_and_seed random 00099] {random 99} "seed normalization"

puts "PASS row-order parser, bounds, and deterministic permutations"
exit
