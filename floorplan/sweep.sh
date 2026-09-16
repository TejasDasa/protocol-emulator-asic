#!/bin/bash
# Each point stops at global routing if congestion remains (GRT_ALLOW_CONGESTION
# is 0), so a failing point costs about 3 minutes.
#
# Points are ordered by what they test, not by expected success:
#   1. the core-margin correction alone, at the original density. Isolates how
#      much of the first failure was the 33,048 um2 of core and 22.68 um of
#      vertical channel that LibreLane's default margins removed.
#   2-3. target density, the parameter lever.
#   4. grouped macros, the floorplan lever: the macros block Metal1-3 and
#      Metal4 is the PDN layer, so above a macro there is nowhere to route.
#      Interleaving makes signals cross four macro shadows; grouping leaves one
#      clear region.
D=/home/tejas/projects/protocol-emulator-asic-competition/floorplan
DS=/nix/store/lrlpbc4nd373kds32zl72fd8qy2ayah0-devshell-dir
export NP_LOCATION=/home/tejas/eda
export NP_RUNTIME=bwrap
NSM=${NSM:-6}
POINTS=${POINTS:-"60 2.0 0.48 interleaved|50 2.0 0.48 interleaved|40 2.0 0.48 interleaved|50 8.0 3.78 grouped|40 8.0 3.78 grouped"}
: > "$D/sweep.log"
IFS='|' read -ra PTS <<< "$POINTS"
for pt in "${PTS[@]}"; do
  set -- $pt
  echo "=== NSM=$NSM density=$1 halo=$2/$3 layout=$4 ===" | tee -a "$D/sweep.log"
  # A point whose config did not regenerate is not a data point. The previous
  # sweep silently re-ran one identical config three times because gen_config.py
  # crashed on a missing file and nothing checked.
  if ! ( cd "$D" && python3 gen_config.py "$NSM" "$1" "$2" "$3" "$4" ) >> "$D/sweep.log" 2>&1; then
    echo "  ABORT: gen_config.py failed, config.json not regenerated" | tee -a "$D/sweep.log"
    exit 1
  fi
  tag="${NSM}_$1_$2_$4"
  /home/tejas/eda/nix-portable nix --extra-experimental-features 'nix-command flakes' \
    shell "$DS" --command bash -c \
    "cd $D && python3 -m librelane --manual-pdk --pdk-root /home/tejas/pdk --pdk ihp-sg13cmos5l --scl sg13cmos5l_stdcell config.json" \
    > "$D/sweep_$tag.log" 2>&1
  rc=$?
  R=$(ls -dt "$D"/runs/*/ | head -1)
  cong=$(grep -A 8 "Final congestion report" "$R"/*globalrouting*/*.log 2>/dev/null \
         | grep "^Total" | tr -s ' ')
  echo "  exit=$rc  run=$(basename $R)  congestion: $cong" | tee -a "$D/sweep.log"
  if [ $rc -eq 0 ]; then
    echo "  CLOSED: density=$1 halo=$2/$3 layout=$4" | tee -a "$D/sweep.log"
    break
  fi
done
echo "=== sweep done ===" | tee -a "$D/sweep.log"
