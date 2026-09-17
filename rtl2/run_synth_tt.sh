#!/bin/bash
# Synthesize rtl2 against sg13cmos5l and run the inferred-latch gate.
# Yosys does not expand environment variables inside a script, so the liberty
# path is templated into a temporary copy of synth_tt.ys.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
LIB=${LIB:-/home/tejas/pdk/ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/lib/sg13cmos5l_stdcell_typ_1p20V_25C.lib}
case "$(basename "$LIB")" in
  sg13cmos5l_*) : ;;
  *) echo "REFUSING: liberty is not sg13cmos5l_*: $LIB"; exit 1 ;;
esac
sed "s|@LIB@|$LIB|g" "$HERE/synth_tt.ys" > "$HERE/.synth_tt.resolved.ys"
cd "$HERE" && yosys -s .synth_tt.resolved.ys
