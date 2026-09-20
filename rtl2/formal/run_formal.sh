#!/bin/bash
# Run every formal task and check it came out the way it is supposed to.
#
# The negative tasks are as load-bearing as the positive ones: a property whose
# assertion cannot fail proves nothing, and this repo has already shipped one
# such gate. So the expected result is written down per task and a break that
# PASSES is a failure of this script, exactly like a property that FAILS.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

# task                     expect  what it is
TASKS=(
  "stt_core:p1:pass:P1 branch resolver agrees with SPEC 5 for every input"
  "stt_core:p1_break_ret:fail:P1 negative -- RET on the true exit only"
  "stt_core:p1_break_skip:fail:P1 negative -- SKIP exits swapped"
)

if [ -f "$HERE/tasks.txt" ]; then
  mapfile -t TASKS < <(grep -v '^\s*#' "$HERE/tasks.txt" | grep -v '^\s*$')
fi

fail=0
printf '%-26s %-8s %-8s %s\n' TASK EXPECT GOT WHAT
for entry in "${TASKS[@]}"; do
  IFS=':' read -r sby task expect what <<< "$entry"
  out=$(timeout 3600 sby -f "$sby.sby" "$task" 2>&1)
  if   echo "$out" | grep -q "DONE (PASS"; then got=pass
  elif echo "$out" | grep -q "DONE (FAIL"; then got=fail
  else got=error; fi
  printf '%-26s %-8s %-8s %s\n' "$task" "$expect" "$got" "$what"
  if [ "$got" != "$expect" ]; then
    fail=1
    echo "$out" | grep -E "ERROR|summary:" | head -5 | sed 's/^/    /'
  fi
done

if [ "$fail" != 0 ]; then
  echo
  echo "FAIL: a formal task did not come out as expected."
  echo "      A 'fail' task that passed means its assertion cannot detect the"
  echo "      bug it is supposed to detect."
  exit 1
fi
echo
echo "OK: every formal property proved, every negative test failed as required"
