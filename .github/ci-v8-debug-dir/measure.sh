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
out=$("${build[@]}" -A v8 2> >(tee build.log >&2))
elapsed=$((SECONDS - start))
"$ccache_bin" --print-stats > stats.txt
hits=$(awk '$1 == "direct_cache_hit" || $1 == "preprocessed_cache_hit" { hits += $2 } END { print hits+0 }' stats.txt)
misses=$(awk '$1 == "cache_miss" { print $2 }' stats.txt)
printf '| Phase | V8 (s) | Hits | Misses |\n|---|---:|---:|---:|\n| %s | %d | %d | %d |\n' \
  "$PHASE" "$elapsed" "$hits" "$misses" >> "$GITHUB_STEP_SUMMARY"

# Ignore only the expected difference in v8.pc's installation prefix.
(
  cd "$out"
  find . -type f | LC_ALL=C sort | while IFS= read -r file; do
    if [[ "$file" == ./lib/pkgconfig/v8.pc ]]; then
      sed "s|^prefix=$out$|prefix=@out@|" "$file" | shasum -a 256 | sed "s|  -$|  $file|"
    else
      shasum -a 256 "$file"
    fi
  done
) > "$PHASE.sha256"
if [[ "$PHASE" == warm ]]; then
  diff -u reference/cold.sha256 warm.sha256
  test "$hits" -gt 0
fi
