import json
import os
import runpy
import sys

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "tools/gyp/pylib"))
import gyp

original = gyp.Load


def capture(*args, **kwargs):
    result = original(*args, **kwargs)
    with open("../results/full-graph.json", "w") as f:
        json.dump(result[2], f, indent=2)
    return result


gyp.Load = capture
sys.argv[0] = "configure.py"
runpy.run_path("configure.py", run_name="__main__")
