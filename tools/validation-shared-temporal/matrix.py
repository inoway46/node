import os
import sys
import pathlib
import subprocess
import tempfile

repo = pathlib.Path.cwd()
sys.path.insert(0, str(repo / "tools/gyp/pylib"))
import gyp

root = pathlib.Path(tempfile.mkdtemp(prefix="shared-temporal-matrix-", dir=None))
for name, content in [
    (
        "before",
        subprocess.check_output(
            ["git", "show", "HEAD:deps/crates/crates.gyp"], cwd=repo
        ),
    ),
    ("after", (repo / "deps/crates/crates.gyp").read_bytes()),
]:
    d = root / name
    d.mkdir()
    (d / "crates.gyp").write_bytes(content)
    (d / "probe.gyp").write_text(
        repr(
            {
                "targets": [
                    {
                        "target_name": "probe",
                        "type": "none",
                        "dependencies": ["crates.gyp:temporal_zoneinfo64_data"],
                    }
                ]
            }
        )
    )
os.environ["GYP_CROSSCOMPILE"] = "1"
original = gyp.Load


class Captured(Exception):
    pass


state = {}


def capture(*a, **kw):
    state["graph"] = original(*a, **kw)[2]
    raise Captured


gyp.Load = capture
count = 0
for generator in ("make", "ninja"):
    for flavor in ("linux", "mac", "win"):
        for profile in ("Release", "Debug"):
            for shared in (None, "false", "true"):
                results = []
                for revision in ("before", "after"):
                    os.chdir(root / revision)
                    opts = [
                        "-DOS=" + flavor,
                        "-Dbuild_type=" + profile,
                        "-Dpython=" + sys.executable,
                    ]
                    if shared is not None:
                        opts.append("-Dnode_shared_temporal_capi=" + shared)
                    try:
                        gyp.main(
                            [
                                "probe.gyp",
                                "--no-parallel",
                                "--depth=.",
                                "-f",
                                generator + "-linux",
                                *opts,
                            ]
                        )
                    except Captured:
                        pass
                    graph = state["graph"]
                    crates = {
                        k: v.get("actions", [])
                        for k, v in graph.items()
                        if ":node_crates#" in k
                    }
                    zone = {
                        k: v.get("actions", [])
                        for k, v in graph.items()
                        if ":temporal_zoneinfo64_data#" in k
                    }
                    assert len(crates) == 2 and len(zone) == 2
                    results.append((crates, zone))
                assert results[0][1] == results[1][1], "Zone data actions changed"
                if shared == "true":
                    assert sum(map(len, results[0][0].values())) == 2
                    assert sum(map(len, results[1][0].values())) == 0
                else:
                    assert results[0] == results[1], "Bundled actions changed"
                count += 1
print(
    f"PASS: {count} before/after graph comparisons; shared Cargo actions removed, bundled/default and zone data actions unchanged"
)
