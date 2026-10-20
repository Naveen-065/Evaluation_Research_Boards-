set here [file dirname [file normalize [info script]]]
open_checkpoint [file join $here build kc705_adc_test.dcp]
report_bus_skew -file [file join $here build bus_skew.rpt]
puts "KC705_ADC_TEST_BUS_SKEW_REPORTED"
exit
