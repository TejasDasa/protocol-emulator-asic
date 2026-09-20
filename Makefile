# Area characterization for the STT protocol emulator on IHP sg13cmos5l.
#
#   make area          run every measurement and print the summary table
#   make area-core     hierarchical + flattened stt_core
#   make area-imem     instruction-memory flop baseline at 32 and 64 rows
#   make area-extras   CRC/LFSR and bit stuffer
#   make check         re-verify the last results (flop mapping, no $-cells)
#   make clean         remove build/
#
# Requires: PDK_ROOT pointing at the IHP-Open-PDK checkout, and yosys on PATH.

PDK_ROOT ?= $(HOME)/pdk
PDK      ?= ihp-sg13cmos5l
SCL      ?= sg13cmos5l_stdcell

# Typical corner, selected because the PDK's own LibreLane config sets
# DEFAULT_CORNER = nom_typ_1p20V_25C in
# $(PDK_ROOT)/$(PDK)/libs.tech/librelane/$(SCL)/config.tcl
LIB ?= $(PDK_ROOT)/$(PDK)/libs.ref/$(SCL)/lib/sg13cmos5l_stdcell_typ_1p20V_25C.lib

YOSYS ?= yosys
RTL   := rtl
BUILD := build

CORE_SRCS := $(RTL)/stt_decode.v $(RTL)/stt_palette.v $(RTL)/stt_datapath.v \
             $(RTL)/stt_imem.v $(RTL)/stt_core.v

FIFO_SRCS := $(CORE_SRCS) $(RTL)/stt_fifo.v $(RTL)/stt_core_fifo.v

.PHONY: area area-core area-imem area-extras check clean lib-check spec spec-check

# ---------------------------------------------------------------- lib check
lib-check:
	@test -f "$(LIB)" || { \
	  echo "ERROR: liberty not found: $(LIB)"; \
	  echo "Set PDK_ROOT. Candidates:"; \
	  find "$(PDK_ROOT)" -name '*.lib' 2>/dev/null | grep -i cmos5l | grep stdcell || true; \
	  exit 1; }
	@grep -qE '^\s*cell \(sg13cmos5l_' "$(LIB)" || { \
	  echo "ERROR: $(LIB) does not contain sg13cmos5l_-prefixed cells."; exit 1; }
	@echo "liberty OK: $(LIB)"
	@echo -n "  cells: "; grep -cE '^\s*cell \(' "$(LIB)"
	@echo -n "  library: "; grep -m1 -oP '^library \(\K[^)]+' "$(LIB)"

# ------------------------------------------------------------------- runs
# $(1) run name  $(2) top  $(3) sources  	     -e 's|@CHPARAM@|$(4)|g' \
	     -e 's|@PRE@|$(6)|g' \
 chparam  $(5) flatten  $(6) pre
define RUN
	@mkdir -p $(BUILD)
	@sed -e 's|@RTL@|$(RTL)|g' \
	     -e 's|@SOURCES@|$(3)|g' \
	     -e 's|@TOP@|$(2)|g' \
	     -e 's|@CHPARAM@|$(4)|g' \
	     -e 's|@PRE@|$(6)|g' \
	     -e 's|@FLATTEN@|$(5)|g' \
	     -e 's|@LIB@|$(LIB)|g' \
	     synth/synth.ys > $(BUILD)/$(1).ys
	@echo "=== $(1) ==="
	@$(YOSYS) -q -l $(BUILD)/$(1).log -s $(BUILD)/$(1).ys 2>&1 | tail -20 || \
	  { echo "YOSYS FAILED for $(1); see $(BUILD)/$(1).log"; exit 1; }
	@python3 scripts/check_area.py $(BUILD)/$(1).log --name $(1) --json $(BUILD)/$(1).json
endef

# Same as RUN but for a design that is legitimately combinational, so the
# "dfflibmap mapped no flops" check must not fire. Used only where the absence
# of flops is the point (e.g. the palette with its action group inlined).
define RUN_COMB
	@mkdir -p $(BUILD)
	@sed -e 's|@RTL@|$(RTL)|g' \
	     -e 's|@SOURCES@|$(3)|g' \
	     -e 's|@TOP@|$(2)|g' \
	     -e 's|@CHPARAM@|$(4)|g' \
	     -e 's|@PRE@|$(6)|g' \
	     -e 's|@FLATTEN@|$(5)|g' \
	     -e 's|@LIB@|$(LIB)|g' \
	     synth/synth.ys > $(BUILD)/$(1).ys
	@echo "=== $(1) ==="
	@$(YOSYS) -q -l $(BUILD)/$(1).log -s $(BUILD)/$(1).ys 2>&1 | tail -20 || \
	  { echo "YOSYS FAILED for $(1); see $(BUILD)/$(1).log"; exit 1; }
	@python3 scripts/check_area.py $(BUILD)/$(1).log --name $(1) --comb-ok --json $(BUILD)/$(1).json
endef

area-core: lib-check
	$(call RUN,core_hier,stt_core,$(CORE_SRCS),,)
	$(call RUN,core_flat,stt_core,$(CORE_SRCS),,flatten -noscopeinfo)

area-imem: lib-check
	$(call RUN,imem32,stt_imem,$(RTL)/stt_imem.v,-chparam ROWS 32 -chparam ADDR_W 5,flatten -noscopeinfo)
	$(call RUN,imem64,stt_imem,$(RTL)/stt_imem.v,-chparam ROWS 64 -chparam ADDR_W 6,flatten -noscopeinfo)

area-extras: lib-check
	$(call RUN,crc_lfsr16,crc_lfsr16,$(RTL)/crc_lfsr16.v,,flatten -noscopeinfo)
	$(call RUN,bit_stuffer,bit_stuffer,$(RTL)/bit_stuffer.v,,flatten -noscopeinfo)

# ---- A1: TIMER_W sweep. Measures the real cost of the timer width, including
# the compare/decrement logic that a flop-count-only estimate misses.
area-timer: lib-check
	$(call RUN,core_timer8,stt_core,$(CORE_SRCS),-chparam TIMER_W 8,flatten -noscopeinfo)
	$(call RUN,core_timer12,stt_core,$(CORE_SRCS),-chparam TIMER_W 12,flatten -noscopeinfo)
	$(call RUN,core_timer16,stt_core,$(CORE_SRCS),-chparam TIMER_W 16,flatten -noscopeinfo)
	$(call RUN,core_timer20,stt_core,$(CORE_SRCS),-chparam TIMER_W 20,flatten -noscopeinfo)
	$(call RUN,core_timer24,stt_core,$(CORE_SRCS),-chparam TIMER_W 24,flatten -noscopeinfo)

# ---- A6: in-core TX/RX FIFOs, i.e. buffering that replicates per state
# machine.  Compare against core_flat, which has no in-core FIFO.
area-fifo: lib-check
	$(call RUN,core_fifo2,stt_core_fifo,$(FIFO_SRCS),-chparam FIFO_DEPTH 2,flatten -noscopeinfo)
	$(call RUN,core_fifo4,stt_core_fifo,$(FIFO_SRCS),-chparam FIFO_DEPTH 4,flatten -noscopeinfo)
	$(call RUN,core_fifo8,stt_core_fifo,$(FIFO_SRCS),-chparam FIFO_DEPTH 8,flatten -noscopeinfo)

# ---- row-width sensitivity: what one more bit in the row actually costs.
# 32-row imem, since that is the configuration the core uses.
area-roww: lib-check
	$(call RUN,roww20,stt_imem,$(RTL)/stt_imem.v,-chparam ROWS 32 -chparam ADDR_W 5 -chparam ROW_W 20,flatten -noscopeinfo)
	$(call RUN,roww21,stt_imem,$(RTL)/stt_imem.v,-chparam ROWS 32 -chparam ADDR_W 5 -chparam ROW_W 21,flatten -noscopeinfo)
	$(call RUN,roww22,stt_imem,$(RTL)/stt_imem.v,-chparam ROWS 32 -chparam ADDR_W 5 -chparam ROW_W 22,flatten -noscopeinfo)
	$(call RUN,roww24,stt_imem,$(RTL)/stt_imem.v,-chparam ROWS 32 -chparam ADDR_W 5 -chparam ROW_W 24,flatten -noscopeinfo)
	$(call RUN,roww29,stt_imem,$(RTL)/stt_imem.v,-chparam ROWS 32 -chparam ADDR_W 5 -chparam ROW_W 29,flatten -noscopeinfo)
	$(call RUN,roww32,stt_imem,$(RTL)/stt_imem.v,-chparam ROWS 32 -chparam ADDR_W 5 -chparam ROW_W 32,flatten -noscopeinfo)

# ---- multi-SM chip: fixed overhead + N x per-SM, at the real TT boundary.
# Fitting a line through these gives a defensible SM count (docs 7).
CHIP_SRCS := $(CORE_SRCS) $(RTL)/stt_fifo.v $(RTL)/stt_hostbuf.v \
             $(RTL)/stt_iomux.v $(RTL)/crc_lfsr16.v $(RTL)/bit_stuffer.v \
             $(RTL)/stt_chip.v

# NOTE: `hierarchy -chparam NSM n` trips a Yosys 0.69 assertion on this top
# (it derives $paramod\\stt_chip\\NSM=n twice). `chparam -set` before
# hierarchy is equivalent and works, so the chip sweep uses $(6) not $(4).
area-chip: lib-check
	$(call RUN,chip1,stt_chip,$(CHIP_SRCS),,flatten -noscopeinfo,chparam -set NSM 1 stt_chip)
	$(call RUN,chip2,stt_chip,$(CHIP_SRCS),,flatten -noscopeinfo,chparam -set NSM 2 stt_chip)
	$(call RUN,chip3,stt_chip,$(CHIP_SRCS),,flatten -noscopeinfo,chparam -set NSM 3 stt_chip)
	$(call RUN,chip4,stt_chip,$(CHIP_SRCS),,flatten -noscopeinfo,chparam -set NSM 4 stt_chip)
	$(call RUN,chip5,stt_chip,$(CHIP_SRCS),,flatten -noscopeinfo,chparam -set NSM 5 stt_chip)
	$(call RUN,chip3_hier,stt_chip,$(CHIP_SRCS),,,chparam -set NSM 3 stt_chip)

# ---- tiled CFGMEM imem: measures the glue the macro does NOT supply.
# The macro is a blackbox, so `stat` here is exactly the retained load path,
# WROW write decode and inter-tile read mux. Its own area is added separately
# on a stated basis (see docs/area-study.md section 5.2).
CFGMEM_SRCS := $(RTL)/cfgmem_ihp16_bb.v $(RTL)/stt_imem_cfgmem.v

area-cfgmem: lib-check
	$(call RUN,cfgmem32,stt_imem_cfgmem,$(CFGMEM_SRCS),,flatten -noscopeinfo,chparam -set NTILE 2 -set ROWS 32 stt_imem_cfgmem)
	$(call RUN,cfgmem64,stt_imem_cfgmem,$(CFGMEM_SRCS),,flatten -noscopeinfo,chparam -set NTILE 4 -set ROWS 64 -set ADDR_W 6 stt_imem_cfgmem)

# ---- row-bit cost under tiled CFGMEM. Storage is 2 macros for any width up to
# 32, so the only width-dependent cost is the glue (staging register + Di path).
area-cfgmem-width: lib-check
	$(call RUN,cfgw21,stt_imem_cfgmem,$(CFGMEM_SRCS),,flatten -noscopeinfo,chparam -set NTILE 2 -set ROWS 32 -set ROW_W 21 stt_imem_cfgmem)
	$(call RUN,cfgw26,stt_imem_cfgmem,$(CFGMEM_SRCS),,flatten -noscopeinfo,chparam -set NTILE 2 -set ROWS 32 -set ROW_W 26 stt_imem_cfgmem)
	$(call RUN,cfgw29,stt_imem_cfgmem,$(CFGMEM_SRCS),,flatten -noscopeinfo,chparam -set NTILE 2 -set ROWS 32 -set ROW_W 29 stt_imem_cfgmem)
	$(call RUN,cfgw32,stt_imem_cfgmem,$(CFGMEM_SRCS),,flatten -noscopeinfo,chparam -set NTILE 2 -set ROWS 32 -set ROW_W 32 stt_imem_cfgmem)

# ---- palette variants: what survives when the 13-bit action group is inlined
# into a 32-bit row (Part B) instead of looked up in a palette.
area-palette: lib-check
	$(call RUN,pal_lookup,stt_palette,$(RTL)/stt_palette.v,,flatten -noscopeinfo,chparam -set INLINE_ENTRY 0 stt_palette)
	$(call RUN_COMB,pal_inline,stt_palette,$(RTL)/stt_palette.v,,flatten -noscopeinfo,chparam -set INLINE_ENTRY 1 stt_palette)

area: area-core area-imem area-extras area-timer area-fifo area-roww area-chip area-cfgmem area-cfgmem-width area-palette
	@python3 scripts/check_slope.py $(BUILD)
	@python3 scripts/summarize_area.py $(BUILD)

# COMB_RUNS are legitimately combinational: the "no flops" check must not fire.
# Listed explicitly rather than pattern-matched, so adding one is a deliberate act.
COMB_RUNS := pal_inline

# ---- specification ---------------------------------------------------------
# docs/SPEC.md is normative and its encoding tables are GENERATED from
# spec/isa.json. Two gates keep the three descriptions of the encoding -- the
# document, the machine-readable source, and the Python models -- from drifting
# apart silently:
#   conformance.py : spec/isa.json   vs  isa_bench/   (models are authoritative)
#   gen_spec.py    : docs/SPEC.md    vs  spec/isa.json
spec-check:
	@python3 spec/conformance.py
	@python3 spec/gen_spec.py --check

spec:
	@python3 spec/gen_spec.py
	@python3 spec/conformance.py

check: spec-check
	@$(MAKE) --no-print-directory rtl2-isa-check
	@$(MAKE) --no-print-directory rtl2-latch
	@$(MAKE) --no-print-directory rtl2-latch-tt
	@$(MAKE) --no-print-directory check-freeze
	@$(MAKE) --no-print-directory check-can
	@$(MAKE) --no-print-directory check-pinmap
	@$(MAKE) --no-print-directory check-phase
	@python3 scripts/check_area.py $(filter-out $(addprefix $(BUILD)/,$(addsuffix .log,$(COMB_RUNS))),$(wildcard $(BUILD)/*.log))
	@for r in $(COMB_RUNS); do \
	   test -f $(BUILD)/$$r.log && python3 scripts/check_area.py $(BUILD)/$$r.log --comb-ok || true; \
	 done
	@python3 scripts/check_slope.py $(BUILD)
	@$(MAKE) --no-print-directory check-mutation

# Mutation score is a validity gate, not a report: if it falls, the benchmarks
# got weaker. That is how the SPI/I2C timing gap survived unnoticed.
check-mutation:
	@cd isa_bench && python3 mutate.py --gate

clean:
	rm -rf $(BUILD)

# The freeze is a claim about encodings, so it gets a gate. freeze_check.py
# re-encodes every reference program and fails if a single packed word moves
# against the committed golden words; nextrow.py fails if a program starts
# taking `next` from its own last row, where the model wraps at the program
# length and the RTL wraps at 32.
.PHONY: check-freeze
check-freeze:
	@cd isa_bench && python3 freeze_check.py
	@cd isa_bench && python3 nextrow.py | tail -1

# CAN is the capability claim the SPEC section 9 wider units were added for, so
# it is a gate too: the transmitter must still fit in 32 rows and still decode
# against an independent CRC-15 and a receiver that is shown to reject
# corrupted frames.
# Phase and jitter in the device models (SPEC section 16.2). The gate is that
# adding them did NOT move the deterministic waveform: every existing result was
# measured against the old fixed-run construction, so the default has to stay
# bit-for-bit what it was. It also checks the knobs actually move edges, since a
# knob that does nothing would pass the first half trivially.
.PHONY: check-phase
check-phase:
	@cd isa_bench && python3 phase_check.py | tail -1
	@cd isa_bench && python3 phase_sweep.py | tail -1

# A pin assignment that cannot work configures cleanly and then does nothing:
# a program using `load`, `push` or `fifo` with no pin selecting the host port
# never moves a byte, and an open-drain slot on uo_out can never release the
# net. Both are decidable from the program and the assignment, so they are
# rejected at construction. Checked in both directions -- a validator that
# cannot fire is worth nothing.
.PHONY: check-pinmap
check-pinmap:
	@cd isa_bench && python3 pinmap_check.py | tail -1

.PHONY: check-can
check-can:
	@cd isa_bench && out=`python3 canrun.py` || { echo "$$out"; exit 1; }; \
	 echo "$$out" | head -1; \
	 echo "OK: CAN 2.0A transmitter decodes against an independent CRC-15, and its receiver rejects corrupted frames"

# ---------------------------------------------------------------- rtl2
# The implementation of the frozen ISA. rtl/ is the previous format's
# measurement harness and is left alone so the area study stays reproducible.
.PHONY: rtl2-isa-check rtl2-latch rtl2-latch-tt rtl2-test rtl2

# The decode constants are generated from spec/isa.json for the same reason the
# encoding tables in docs/SPEC.md are: a hand-copied constant is a silent
# divergence waiting to happen.
rtl2-isa-check:
	@python3 rtl2/gen_isa_vh.py --check

# Fails on ANY inferred latch. An accidental latch in the section 8.1 datapath,
# which is almost entirely combinational, is the classic way a design that
# simulates correctly fails in silicon. Verified in both directions: deleting
# the default assignment in the pin-op block makes this fail with
# "Assertion failed: selection is not empty: t:$$dlatch".
rtl2-latch: lib-check
	@LIB=$(LIB) bash rtl2/run_synth.sh > rtl2/synth.log 2>&1 || \
	  { echo "rtl2 LATCH GATE FAILED; see rtl2/synth.log"; \
	    grep -E "Latch inferred|Assertion failed" rtl2/synth.log | head -5; exit 1; }
	@grep -q "no inferred latches" rtl2/synth.log || \
	  { echo "rtl2: latch gate did not run"; exit 1; }
	@echo "OK: rtl2 has no inferred latches"
	@grep -E "Chip area for module" rtl2/synth.log | tail -1

# The same gate over the WHOLE chip, up to tt_um_stt. stt_top alone leaves the
# iomux, the host port and the chip glue unguarded, and the iomux's pin decode
# is exactly the shape that infers a latch if a branch is ever missed.
rtl2-latch-tt: lib-check
	@LIB=$(LIB) bash rtl2/run_synth_tt.sh > rtl2/synth_tt.log 2>&1 || \
	  { echo "rtl2 WHOLE-CHIP LATCH GATE FAILED; see rtl2/synth_tt.log"; \
	    grep -E "Latch inferred|Assertion failed|ERROR" rtl2/synth_tt.log | head -5; exit 1; }
	@grep -q "no inferred latches" rtl2/synth_tt.log || \
	  { echo "rtl2: whole-chip latch gate did not run"; exit 1; }
	@echo "OK: rtl2 has no inferred latches up to tt_um_stt"
	@grep -E "Chip area for module ..tt_um_stt" rtl2/synth_tt.log | tail -1

# Cycle-exact lockstep against the authoritative models. Needs cocotb and a
# simulator, so it is a separate target: see rtl2/README.md for the environment.
rtl2-test:
	@cd rtl2 && $(COCOTB_PY) tb/run_tests.py

rtl2: rtl2-isa-check rtl2-latch rtl2-test

COCOTB_PY ?= python3

# Mutation and random-program lockstep. Both need cocotb and a simulator, so
# like rtl2-test they are separate from `make check`.
.PHONY: rtl2-mutants rtl2-random rtl2-full
rtl2-mutants:
	@cd rtl2 && $(COCOTB_PY) tb/run_mutants.py
rtl2-random:
	@cd rtl2 && $(COCOTB_PY) tb/run_random.py
rtl2-full: rtl2-isa-check rtl2-latch rtl2-test rtl2-mutants rtl2-random rtl2-multi rtl2-fifo rtl2-chip rtl2-slope

# Replication: NSM independent machines. rtl2-multi loads a DIFFERENT reference
# program into each and checks every one against its own model each cycle, so a
# load reaching the wrong machine or instances that leaked cannot pass.
# rtl2-slope is the structural counterpart: N machines must cost exactly N times
# one machine, or synthesis merged them (docs/area-study.md).
.PHONY: rtl2-multi rtl2-slope
rtl2-multi:
	@cd rtl2 && $(COCOTB_PY) tb/run_multi.py
	@cd rtl2 && IMEM=cfgmem $(COCOTB_PY) tb/run_multi.py

rtl2-slope: lib-check
	@cd rtl2 && for n in 1 2 5; do \
	   NSM=$$n LIB=$(LIB) bash run_synth_array.sh > slope_$$n.log 2>&1 || \
	     { echo "array synthesis failed at NSM=$$n"; exit 1; }; \
	 done
	@cd rtl2 && python3 check_slope.py slope_1.log slope_2.log slope_5.log

# The Tiny Tapeout boundary: pin assignment, the run flag, five machines
# configured the way a host actually would -- through the pins, in order.
.PHONY: rtl2-chip
rtl2-chip:
	@cd rtl2 && $(COCOTB_PY) tb/run_chip.py

# Does the instruction memory hold what was shifted into it? Every lockstep
# suite loads through this one path, so a load that drops bits is invisible to
# all of them -- the machine simply sits still. test_skew reimplemented the
# shift loop without the settle past the clock edge, read imem_ld_busy as it
# was before the edge, and lost exactly one bit per 32-bit word boundary.
.PHONY: rtl2-imemload
rtl2-imemload:
	@cd rtl2 && $(COCOTB_PY) tb/run_imemload.py

# Directed hostbuf test: depth, overflow, underflow, sticky flags. The chip
# test never fills a FIFO -- that is what depth 4 is for -- so the boundary
# behaviour SPEC section 9 specifies needs its own test.
.PHONY: rtl2-fifo
rtl2-fifo:
	@cd rtl2 && $(COCOTB_PY) tb/run_fifo.py
