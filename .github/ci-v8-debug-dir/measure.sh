#!/usr/bin/env bash
set -euo pipefail

build=(nix-build --no-out-link .github/ci-v8-debug-dir/experiment.nix --argstr tarDir "$TAR_DIR")
ccache_bin=$("${build[@]}" -A ccache)/bin/ccache
export CCACHE_DIR="${CACHE_DIR:?}" CCACHE_UMASK=000

if [[ "$PHASE" == cold ]]; then
  a=$("${build[@]}" -A probeA)
  b=$("${build[@]}" -A probeB)
  cmp "$a/probe.o" "$b/probe.o"
  dwarfdump --debug-info "$b/probe.o" > dwarf.txt
  grep 'DW_AT_comp_dir' dwarf.txt | grep -F '(".")'
  grep -F 'DW_TAG_subprogram' dwarf.txt
  "$ccache_bin" --print-stats | awk '$1 == "direct_cache_hit" || $1 == "preprocessed_cache_hit" { hits += $2 } END { exit hits != 1 }'
fi
"$ccache_bin" --zero-stats
start=$SECONDS
if [[ "$PHASE" == cold ]]; then
  python3 .github/ci-v8-debug-dir/checkpoint.py "${build[@]}" -A v8
else
  (while :; do
    "$ccache_bin" --print-stats > live-stats.tmp
    mv live-stats.tmp live-stats.txt
    sleep 60
  done) &
  monitor=$!
  trap 'kill "$monitor" 2>/dev/null || true' EXIT
  out=$("${build[@]}" -A v8 2> >(tee build.log >&2))
  test -s "$out/lib/pkgconfig/v8.pc"
  ls "$out"/lib/*.a > libraries.txt
fi
elapsed=$((SECONDS - start))
"$ccache_bin" --print-stats > stats.txt
hits=$(awk '$1 == "direct_cache_hit" || $1 == "preprocessed_cache_hit" { hits += $2 } END { print hits+0 }' stats.txt)
misses=$(awk '$1 == "cache_miss" { print $2 }' stats.txt)
printf '| Phase | V8 (s) | Hits | Misses |\n|---|---:|---:|---:|\n| %s | %d | %d | %d |\n' \
  "$PHASE" "$elapsed" "$hits" "$misses" >> "$GITHUB_STEP_SUMMARY"

if [[ "$PHASE" == warm ]]; then
  awk -v h="$hits" -v m="$misses" 'BEGIN {printf "Hit rate: %.1f%% (%d hits, %d misses)\n", 100*h/(h+m ? h+m : 1),h,m}' >> "$GITHUB_STEP_SUMMARY"
fi
test "$misses" -gt 0 || test "$PHASE" = warm
