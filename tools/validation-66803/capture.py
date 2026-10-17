"""Record the resolved GYP graph while using the real generator."""
import json
import os
from pathlib import Path
import runpy
import sys

root = Path.cwd()
sys.path[:0] = [str(root / 'tools/gyp/pylib'), str(root / 'tools/v8_gypfiles')]
import gyp

original = gyp.Load


def capture(*args, **kwargs):
    result = original(*args, **kwargs)
    fields = ['target_name', 'toolset', 'dependencies', 'actions', 'sources']
    graph = {key: {name: value for name, value in target.items() if name in fields} for key, target in result[2].items()}
    Path(os.environ['TASK_GRAPH_JSON']).write_text(json.dumps(graph, indent=2))
    return result


gyp.Load = capture
sys.argv = ['tools/gyp_node.py', *sys.argv[1:]]
runpy.run_path('tools/gyp_node.py', run_name='__main__')
