#!/bin/bash
# Usage: NSM=5 bash run_synth_array.sh
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
NSM=${NSM:-5}
LIB=${LIB:-/home/tejas/pdk/ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/lib/sg13cmos5l_stdcell_typ_1p20V_25C.lib}
case "$(basename "$LIB")" in sg13cmos5l_*) : ;; *) echo "REFUSING: $LIB"; exit 1;; esac
sed -e "s|@LIB@|$LIB|g" -e "s|@NSM@|$NSM|g" \
    "$HERE/synth_array.ys" > "$HERE/.synth_array.resolved.ys"
cd "$HERE" && yosys -s .synth_array.resolved.ys
