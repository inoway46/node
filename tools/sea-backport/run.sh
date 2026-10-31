#!/bin/sh
# Runs both on the host (PAYLOAD=payload) and as part of the minimal guest.
cd "${PAYLOAD:-/}" || exit 1
ulimit -c 0
page=$(getconf PAGESIZE)
echo "PAGE_SIZE=$page EXPECTED=$EXPECTED_PAGE"
uname -a
ok=1
[ "$page" = "$EXPECTED_PAGE" ] || ok=0
./node --version > /tmp/node-version.txt 2>&1
rc=$?
cat /tmp/node-version.txt
echo "NODE_EXIT=$rc"
[ "$rc" = 0 ] && grep -Fxq v26.13.0 /tmp/node-version.txt || ok=0
./node --build-sea sea.json > /tmp/generate.txt 2>&1
rc=$?
cat /tmp/generate.txt
echo "GENERATE_EXIT=$rc"
[ "$rc" = 0 ] || ok=0
readelf -h -l -W regenerated
./node check-elf.cjs regenerated "$page"
rc=$?
echo "REGENERATED_LAYOUT_EXIT=$rc"
[ "$rc" = 0 ] || ok=0
for variant in official patched regenerated; do
  timeout 120 "./$variant" > /tmp/sea.out 2> /tmp/sea.err
  rc=$?
  echo "RESULT variant=$variant page=$page sea_exit=$rc"
  cat /tmp/sea.out /tmp/sea.err
  if [ "$variant" != official ]; then
    [ "$rc" = 0 ] && grep -Fxq 'hello from sea v26.13.0' /tmp/sea.out || ok=0
  elif [ "$rc" = 0 ]; then
    echo "NEGATIVE_CONTROL_SUCCEEDED page=$page"
  fi
  if [ "$rc" != 0 ] && command -v strace >/dev/null; then
    timeout 30 strace -f -e trace=execve "./$variant" 2>&1
  fi
done
[ "$ok" = 1 ] || { echo SEA_BACKPORT_FAIL; exit 1; }
echo SEA_BACKPORT_PASS
