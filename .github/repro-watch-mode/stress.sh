#!/bin/bash
# Run one test file repeatedly with several concurrent workers, optionally
# with CPU burners, and keep the output of every run that did not pass.
#
# Usage: stress.sh <node> <test-file> <workers> <iterations-per-worker>
#                  <timeout-seconds> <burners> <out-dir>
# Run it from the directory that contains `test/`.
set -u

NODE=$1 TEST=$2 WORKERS=$3 ITERATIONS=$4 TIMEOUT=$5 BURNERS=$6 OUT=$7
mkdir -p "$OUT"

# Runs a command in its own process group and kills the whole group (including
# `node --watch` children) when it exceeds the timeout. Exit code 124 = timeout.
run_with_timeout() {
  perl -e '
    my $t = shift;
    my $pid = fork();
    if ($pid == 0) { setpgrp(0, 0); exec @ARGV; exit 127; }
    $SIG{ALRM} = sub { kill "KILL", -$pid; waitpid($pid, 0); exit 124; };
    alarm $t;
    waitpid($pid, 0);
    exit($? & 127 ? 128 + ($? & 127) : $? >> 8);
  ' "$@"
}

burners=()
for ((b = 0; b < BURNERS; b++)); do
  (while :; do :; done) &
  burners+=($!)
done

worker() {
  local id=$1 i rc log start
  for ((i = 0; i < ITERATIONS; i++)); do
    log="$OUT/w$id-i$i.log"
    start=$SECONDS
    TEST_THREAD_ID="w$id" run_with_timeout "$TIMEOUT" \
      "$NODE" --expose-internals --test-reporter=spec "$TEST" > "$log" 2>&1
    rc=$?
    if [ "$rc" -eq 0 ]; then
      rm -f "$log"
      echo pass >> "$OUT/.results-w$id"
    else
      [ "$rc" -eq 124 ] && echo "--- TIMEOUT after ${TIMEOUT}s ---" >> "$log"
      echo "fail rc=$rc" >> "$OUT/.results-w$id"
      echo "FAIL worker=$id iteration=$i rc=$rc ($((SECONDS - start))s)"
    fi
  done
}

workers=()
for ((w = 0; w < WORKERS; w++)); do
  worker "$w" &
  workers+=($!)
done
wait "${workers[@]}"
if [ "${#burners[@]}" -gt 0 ]; then
  kill "${burners[@]}" 2> /dev/null
  wait "${burners[@]}" 2> /dev/null
fi

total=$(cat "$OUT"/.results-w* | wc -l | tr -d ' ')
failed=$(grep -c '^fail' "$OUT"/.results-w* /dev/null | awk -F: '{ s += $2 } END { print s + 0 }')
timeouts=$(grep -h -c 'rc=124' "$OUT"/.results-w* /dev/null | awk '{ s += $1 } END { print s + 0 }')
rm -f "$OUT"/.results-w*
echo "runs=$total failed=$failed timeouts=$timeouts" | tee "$OUT/summary.txt"
[ "$failed" -eq 0 ]
