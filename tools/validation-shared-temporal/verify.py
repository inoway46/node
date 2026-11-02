import json
from pathlib import Path

graph = json.loads(Path("../results/full-graph.json").read_text())
crates = [v for k, v in graph.items() if ":node_crates#" in k]
assert len(crates) == 2
assert all(not v.get("actions") for v in crates)
node = [v for k, v in graph.items() if k.endswith(":node#target")]
assert len(node) == 1
assert "libnode_crates" not in str(node[0].get("libraries", []))
zone = [v for k, v in graph.items() if ":temporal_zoneinfo64_data#" in k]
assert len(zone) == 2 and all(v.get("actions") for v in zone)
print("PASS: full configure graph has no Cargo actions or bundled Rust link input")
