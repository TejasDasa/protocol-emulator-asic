#!/bin/bash
# The formal code must not reach synthesis.
#
# Check 1 (always): production synthesis, which never defines FORMAL, emits no
# assert/assume/anyseq/cover cells. This is the permanent gate.
#
# Check 2 (with --ref): the synthesized netlist is byte-identical to that of a
# reference copy of the same file. Used once, when the formal code was added,
# to show it changed no synthesizable logic. Both copies are synthesized from
# the SAME path and with `src` attributes stripped, because yosys derives
# netlist names and attributes from the source location, and those differences
# are naming rather than logic.
#
#   ./check_synth_clean.sh
#   ./check_synth_clean.sh --ref <file.v>
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
RTL="$(dirname "$HERE")"
REF=""
[ "${1:-}" = "--ref" ] && REF="$2"

synth_to () {   # <source.v> <out.json> [extra defines]
  yosys -qp "read_verilog -I $RTL ${3:-} $1; synth -top stt_core; \
             setattr -mod -unset src; setattr -unset src; write_json $2"
}

SAME=/tmp/f_same_stt_core.v
cp "$RTL/stt_core.v" "$SAME"; synth_to "$SAME" /tmp/f_now.json

bad=$(grep -c '"\$\(assert\|assume\|anyseq\|anyconst\|live\|cover\)"' /tmp/f_now.json || true)
if [ "$bad" != "0" ]; then
  echo "FAIL: production synthesis contains $bad verification cells"
  exit 1
fi
echo "OK: no assert/assume/anyseq cells in production synthesis"

[ -z "$REF" ] && exit 0

cp "$REF" "$SAME"; synth_to "$SAME" /tmp/f_ref.json
if cmp -s /tmp/f_now.json /tmp/f_ref.json; then
  echo "OK: synthesized netlist byte-identical to $REF"
else
  echo "FAIL: synthesized netlist differs from $REF"
  diff /tmp/f_ref.json /tmp/f_now.json | head -30
  exit 1
fi
