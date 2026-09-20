#!/bin/bash
# The formal code must not reach synthesis.
#
# Check 1 (always): production synthesis, which never defines FORMAL, emits no
# assert/assume/anyseq/cover cells for any module that carries formal code.
# This is the permanent gate.
#
# Check 2 (with --ref): the synthesized netlist of stt_core is byte-identical
# to that of a reference copy. Used once, when the formal code was added, to
# show it changed no synthesizable logic. Both copies are synthesized from the
# SAME path and with `src` attributes stripped, because yosys derives netlist
# names and attributes from the source location, and those differences are
# naming rather than logic.
#
#   ./check_synth_clean.sh
#   ./check_synth_clean.sh --ref <file.v>
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
RTL="$(dirname "$HERE")"
REF=""
[ "${1:-}" = "--ref" ] && REF="$2"

MODULES="stt_core stt_fifo"
VCELLS='"\$(assert|assume|anyseq|anyconst|live|cover)"'

synth_to () {   # <source.v> <out.json> <top>
  yosys -qp "read_verilog -I $RTL $1; synth -top $3; setattr -mod -unset src; setattr -unset src; write_json $2"
}

for m in $MODULES; do
  same="/tmp/f_same_$m.v"
  cp "$RTL/$m.v" "$same"
  synth_to "$same" "/tmp/f_now_$m.json" "$m"
  bad=$(grep -cE "$VCELLS" "/tmp/f_now_$m.json" || true)
  if [ "$bad" != "0" ]; then
    echo "FAIL: production synthesis of $m contains $bad verification cells"
    exit 1
  fi
done
echo "OK: no assert/assume/anyseq cells in production synthesis ($MODULES)"

[ -z "$REF" ] && exit 0

same=/tmp/f_same_stt_core.v
cp "$REF" "$same"
synth_to "$same" /tmp/f_ref.json stt_core
if cmp -s /tmp/f_now_stt_core.json /tmp/f_ref.json; then
  echo "OK: stt_core netlist byte-identical to $REF"
else
  echo "FAIL: stt_core netlist differs from $REF"
  diff /tmp/f_ref.json /tmp/f_now_stt_core.json | head -30
  exit 1
fi
