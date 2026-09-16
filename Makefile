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

.PHONY: area area-core area-imem area-extras check clean lib-check

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

area: area-core area-imem area-extras area-timer area-fifo area-roww area-chip area-cfgmem area-cfgmem-width
	@python3 scripts/check_slope.py $(BUILD)
	@python3 scripts/summarize_area.py $(BUILD)

check:
	@python3 scripts/check_area.py $(BUILD)/*.log
	@python3 scripts/check_slope.py $(BUILD)

clean:
	rm -rf $(BUILD)
