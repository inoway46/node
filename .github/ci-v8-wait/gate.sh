#!/usr/bin/env bash
# Fork-only prototype (inoway46/node); not for upstream.
#
# Decides whether a shared-library job should start now, or first wait for
# someone else (normally the push run on the base branch) to put V8 into the
# binary cache.
#
# Environment:
#   V8_PATH    store path of the V8 this run needs
#   HEAD_PATH  V8 store path evaluated from the head checkout
#   BASE_PATH  V8 store path evaluated from the base checkout
#   CACHE_URL  binary cache URL
#   CAN_PUSH   "true" when this run can push to the binary cache
#   MAX_WAIT   maximum time to wait, in seconds
#   INTERVAL   time between two polls, in seconds
#
# Prints "decision=..." and "waited=..." (seconds), and appends them to
# $GITHUB_OUTPUT when it is set.
set -euo pipefail

narinfo_status() {
  curl -ISs -o /dev/null -w '%{http_code}' \
    "$CACHE_URL/$(basename "${V8_PATH%-v8-*}").narinfo" || true
}

waited=0
if [ "$(narinfo_status)" = 200 ]; then
  # Nothing to build.
  decision=cached
elif [ "$CAN_PUSH" = true ]; then
  # This is the run everyone else is waiting for.
  decision=build-and-push
elif [ "$HEAD_PATH" != "$BASE_PATH" ]; then
  # This change is what invalidated V8: nobody else is going to build it.
  decision=build-own-change
else
  # The base branch needs the same V8 and it is not cached yet: its push run
  # is most likely building it right now. Wait for it instead of duplicating
  # a multi-hour build.
  decision=build-after-timeout
  start=$SECONDS
  while [ $((SECONDS - start)) -lt "$MAX_WAIT" ]; do
    sleep "$INTERVAL"
    if [ "$(narinfo_status)" = 200 ]; then
      decision=cached-after-wait
      break
    fi
  done
  waited=$((SECONDS - start))
fi

echo "decision=$decision"
echo "waited=$waited"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  {
    echo "decision=$decision"
    echo "waited=$waited"
  } >> "$GITHUB_OUTPUT"
fi
