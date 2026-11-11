set dcp {C:/Users/fpga.DESKTOP-CVDV1JP/kc705_vadj/build/kc705_vadj_bridge.dcp}
open_checkpoint $dcp
foreach p {pmbus_scl pmbus_sda} {
    set port [get_ports $p]
    puts "PORT $p PACKAGE_PIN=[get_property PACKAGE_PIN $port] IOSTANDARD=[get_property IOSTANDARD $port]"
    set iob [get_cells -quiet -of_objects $port]
    puts "CELLS $p $iob"
    foreach c $iob { puts "CELL $c LOC=[get_property LOC $c] BEL=[get_property BEL $c] IS_LOC_FIXED=[get_property IS_LOC_FIXED $c]" }
    set nets [get_nets -quiet -of_objects $port]
    puts "NETS $p $nets"
    set pins [get_pins -quiet -of_objects $nets]
    puts "PINS $p $pins"
    foreach c [get_cells -quiet -of_objects $pins] {
        puts "NETCELL $p $c REF=[get_property REF_NAME $c] LOC=[get_property LOC $c] BEL=[get_property BEL $c]"
    }
}
puts "DESIGN_ROUTED=[get_property IS_ROUTE_DESIGN [current_design]]"
foreach c [get_cells -hier -filter {REF_NAME == IBUF || REF_NAME == OBUFT || REF_NAME == IOBUF || REF_NAME == OBUF}] {
    puts "IOCELL $c REF=[get_property REF_NAME $c] LOC=[get_property LOC $c] BEL=[get_property BEL $c]"
    foreach p [get_pins -quiet -of_objects $c] {
        puts "  PIN $p DIR=[get_property DIRECTION $p] NET=[get_nets -quiet -of_objects $p]"
    }
}
exit
