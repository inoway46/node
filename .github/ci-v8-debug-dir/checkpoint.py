"""Stop nix-build after Ninja reports enough completed build edges."""
import re
import signal
import subprocess
import sys

with open("build.log", "w") as log, subprocess.Popen(
    sys.argv[1:], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    errors="replace",
) as build:
    stopped = False
    for line in build.stdout:
        print(line, end="", flush=True)
        log.write(line)
        progress = re.search(r"\[(\d+)/(\d+)\]", line)
        if progress and not stopped:
            done, total = map(int, progress.groups())
            if 800 <= done < total and total >= 1000:
                build.send_signal(signal.SIGINT)
                stopped = True
    status = build.wait()
    if not stopped or status == 0:
        sys.exit(f"Expected an interrupted V8 build, got status {status}")
