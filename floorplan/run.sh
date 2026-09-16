#!/bin/bash
# Environment recovered from the COMMANDS files of the pdn_test run that worked:
# everything came from /nix/store/6a08...-python3-3.13.13-env, i.e. LibreLane's
# own devshell, which is cached at the store path below. Enter it by store path
# rather than `nix develop github:librelane/librelane` -- upstream HEAD has moved
# and re-resolving the flake starts compiling OpenROAD from source.
#
# Not the dffram flake: it pins librelane 2.4.2, whose pyosys has no Pass.call
# and whose schema wants FILL_CELL where sg13cmos5l sets FILL_CELLS.
# Not ~/venv-lrl: 3.1.0.dev3 on system Python 3.12, which has no tkinter, and
# LibreLane needs tkinter to evaluate the PDK's config.tcl.
# NP_RUNTIME=bwrap: the auto-selected "nix" runtime fails with
# "setting up a private mount namespace: Operation not permitted".
D=/home/tejas/projects/protocol-emulator-asic-competition/floorplan
DS=/nix/store/lrlpbc4nd373kds32zl72fd8qy2ayah0-devshell-dir
export NP_LOCATION=/home/tejas/eda
export NP_RUNTIME=bwrap
/home/tejas/eda/nix-portable nix --extra-experimental-features 'nix-command flakes' \
  shell "$DS" --command bash -c \
  "cd $D && python3 -m librelane --manual-pdk --pdk-root /home/tejas/pdk --pdk ihp-sg13cmos5l --scl sg13cmos5l_stdcell config.json" \
  > "$D/run6.log" 2>&1
echo "EXIT $?" >> "$D/run6.log"
