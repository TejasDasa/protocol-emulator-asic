# Per-output-pin clock-to-output delay on the signed-off design.
#
# STATIC, not simulated. Gate-level simulation was brought up far enough to
# annotate SDF and resolve real picoseconds on the clock tree
# (rtl2/sdf/README.md), but the machines never reached a state where they drive
# pins, so the numbers here come from the same OpenSTA that signed the design
# off rather than from a waveform.
#
# Skew between two pins is the difference in their clock-to-output delays, so
# reporting the delay per pin gives every pair.
define_corners $::env(CORNER)
foreach l [split $::env(LIBS) " "] { read_liberty -corner $::env(CORNER) $l }
read_verilog $::env(PNR_RUN)/final/nl/tt_um_stt.nl.v
link_design tt_um_stt
read_spef -corner $::env(CORNER) $::env(PNR_RUN)/final/spef/nom/tt_um_stt.nom.spef
read_sdc $::env(PNR_RUN)/final/sdc/tt_um_stt.sdc

puts "PINSKEW-CORNER $::env(CORNER)"
set outs {}
foreach o [all_outputs] { lappend outs [get_full_name $o] }
foreach port [lsort $outs] {
    foreach mode {max min} {
        puts "PINSKEW-BEGIN $port $mode"
        report_checks -to [get_ports $port] -path_delay $mode \
                      -group_count 1 -digits 4 -corner $::env(CORNER)
        puts "PINSKEW-END"
    }
}
exit
