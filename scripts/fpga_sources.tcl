# FPGA bring-up source list for stt_fpga_top.
#
# FPGA BRING-UP INFRASTRUCTURE. Not part of the ASIC submission.
#
# Run this from the Vivado Tcl Console after pulling, with STT_ROOT pointing at
# the repo root:
#
#   set STT_ROOT /path/to/protocol-emulator-asic-competition
#   source $STT_ROOT/scripts/fpga_sources.tcl
#
# Safe to re-run: it only adds files the project does not already have. It
# exists because a new module is invisible to Vivado until someone adds it, and
# the failure is "module not found" at elaboration rather than anything that
# points at the cause -- stt_hostread.v did exactly that when it was added.

if {![info exists STT_ROOT]} {
    error "set STT_ROOT to the repo root first"
}
set rtl $STT_ROOT/rtl2

# Order does not matter; update_compile_order sorts it out.
set srcs {
    stt_fpga_top.v
    stt_loader.v
    stt_hostread.v
    tt_um_stt.v
    stt_chip.v
    stt_array.v
    stt_top.v
    stt_core.v
    stt_config.v
    stt_imem.v
    stt_iomux.v
    stt_fifo.v
    stt_hostbuf.v
    stt_hostport.v
}

# NOT in this list, deliberately:
#   stt_top_cfgmem.v, stt_imem_cfgmem.v, cfgmem_ihp16_*.v
#       the CFGMEM macro path. There are no such macros on a Zynq; the
#       behavioural imem is what the FPGA build uses.
#   tb/fpga_sim_stubs.v
#       simulation stubs for clk_wiz_0 and BUFG. Vivado binds the REAL
#       Clocking Wizard IP; adding the stub would shadow it and give you a
#       toggle divider with no timing constraints, which is the fault that
#       produced 300 baud instead of 9600.

set added {}
foreach f $srcs {
    set p [file normalize $rtl/$f]
    if {![file exists $p]} { error "missing source: $p" }
    if {[llength [get_files -quiet $p]] == 0} {
        add_files -norecurse $p
        lappend added $f
    }
}

# stt_fpga_top.v and stt_loader.v both `include "stt_rom.vh"`, and the RTL
# includes "stt_isa.vh", so rtl2 has to be on the include path.
set_property include_dirs [list [file normalize $rtl]] [get_filesets sources_1]

foreach h {stt_rom.vh stt_isa.vh} {
    set p [file normalize $rtl/$h]
    if {[llength [get_files -quiet $p]] == 0} {
        add_files -norecurse -fileset sources_1 $p
    }
    set_property file_type {Verilog Header} [get_files $p]
}

# STT_NSM is a `define, not a parameter, so it cannot be set from the wrapper.
# It MUST match the machine count the ROM was generated for, or the
# pin-assignment chain is the wrong length and nothing runs: the loopback ROM
# is 74 bits at NSM=2, against 50 at NSM=1.
if {![info exists STT_NSM]} { set STT_NSM 2 }
set_property verilog_define "STT_NSM=$STT_NSM" [get_filesets sources_1]

update_compile_order -fileset sources_1
set_property top stt_fpga_top [get_filesets sources_1]

puts "STT: [llength $added] file(s) added: $added"
puts "STT: STT_NSM=$STT_NSM, include_dirs=[file normalize $rtl]"
puts "STT: LOOPBACK_INTERNAL defaults to 1 (internal route)."
puts "STT: for the external jumper, set the generic on the synth run:"
puts "STT:   set_property -name {STEPS.SYNTH_DESIGN.ARGS.MORE OPTIONS} \\"
puts "STT:     -value {-generic LOOPBACK_INTERNAL=0} -objects \[get_runs synth_1\]"
