#!/bin/bash
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
LIB=${LIB:-/home/tejas/pdk/ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/lib/sg13cmos5l_stdcell_typ_1p20V_25C.lib}
case "$(basename "$LIB")" in sg13cmos5l_*) : ;; *) echo "REFUSING: $LIB"; exit 1;; esac
sed "s|@LIB@|$LIB|g" "$HERE/synth_cfgmem.ys" > "$HERE/.synth_cfgmem.resolved.ys"
cd "$HERE" && yosys -s .synth_cfgmem.resolved.ys
