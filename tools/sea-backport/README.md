# Node v26.13.0 / LIEF 5da7685 SEA experiment

Base: Node v26.13.0, commit `18b32a3b1552e199a01f1a8d9fd64aa756d3b75b`.
Upstream patch: `5da76859ef9272689a13a2669746d15391cde03a`.

All eight upstream C++ implementation/header changes are included. Upstream
Sphinx documentation and Python tests are excluded from the vendored dependency.
The layout_check.cpp include hunk needs manual placement because the include order
in the vendored 1.0.0 differs. No other upstream commit, Node SEA change, or
additional behavioral fix is included. Existing Node modifications are retained.
No new translation units are introduced; paging.cpp and layout_check.cpp already
appear in lief.gyp, so no GYP/GN source-list changes are needed.

The workflow reuses kernel acquisition, initramfs assembly, and QEMU system
emulation from inoway46/LIEF run 41143675426 and GNU ld build conditions from
inoway46/node run 41091181151. GNU ld produces the single BSS-like LOAD required
by LIEF's existing BSS_END relocation; changing the linker is an explicit build
condition, not a LIEF source fix. Builds are non-PIE with 64 KiB maximum/common
linker page alignment. Rust 1.88 and four parallel compilation jobs match the
existing source-build probe. The official binary remains the negative control.

## Build and reuse

Workflow: `.github/workflows/sea-lief-backport.yml`.
The initial branch push builds automatically. Subsequent dispatches:

```sh
gh workflow run sea-lief-backport.yml -R inoway46/node \
  --ref codex/sea-v26.13.0-lief-5da7685 -f mode=build-and-verify

gh workflow run sea-lief-backport.yml -R inoway46/node \
  --ref codex/sea-v26.13.0-lief-5da7685 \
  -f mode=verify-only -f source_run_id=RUN_ID
```

The reusable artifact is `node-v26.13.0-linux-arm64-lief-5da7685`:

```sh
gh run download RUN_ID -R inoway46/node \
  -n node-v26.13.0-linux-arm64-lief-5da7685 -D restored
cd restored
sha256sum -c products.tar.gz.sha256
tar -xzf products.tar.gz
sha256sum -c SHA256SUMS
cat metadata.json
./out/Release/node --version
./payload/patched
./payload/official
EXPECTED_PAGE=$(getconf PAGESIZE) PAYLOAD=payload sh payload/run.sh
```

Use Linux arm64 with compatible glibc/libstdc++; build-time `ldd` results and
configuration are in build-evidence. Dynamic libraries come from the runner OS;
the QEMU initramfs copies their resolved paths for both Node binaries. Other
workflows can use actions/download-artifact with the artifact name, `run-id`,
`repository: inoway46/node`, and an appropriately authorized GitHub token. Same
repository GITHUB_TOKEN needs `actions: read`; private-repository local access
requires an account/token with repository access. Download failure (including
missing or expired artifacts) fails verification; it never triggers a rebuild.

Artifacts expire after 30 days (or earlier manual deletion). Verify-only checks
the archive and every packaged file SHA256 and enforces the Node base SHA,
version, arm64 architecture label, and exact LIEF patch SHA. The ELF inspector
also verifies AArch64 machine type. SHA256 detects corruption; trust in the
producer run and repository is still required. The artifact includes the build
source SHA, build configuration, patch diff, logs, official and patched SEA, and
`out/Release/node`. Choose the same branch revision for reproducible harness
behavior; verify-only records the producer metadata independently.

## Evidence and interpretation

Each verifier downloads the same tar.gz. 4 KiB runs on the runner; 16/64 KiB boot
real distribution kernels using QEMU system emulation, not user emulation. Each
kernel must report the requested actual page size. All run Node, regenerate SEA
with that Node, and run both the stored and freshly regenerated patched SEA,
checking exit 0 and exactly `hello from sea v26.13.0`. Official control exit status
and unexpected success are recorded without requiring the control to crash.
ELF checks inspect address/file-offset congruence and virtual-page overlap for
all stored executables at the target page size; 4 KiB also inspects regenerated
SEA. Guest generation and executions are captured on the serial console; failed
executions include execve strace. A green build alone establishes no SEA result.
Evidence artifacts also retain build logs on build failure.

The guest prints readelf output and validates freshly regenerated SEA layouts
using the patched Node itself. Its ephemeral generated file is not exported;
the producer's SEA is retained in the reusable artifact. Broader Node CI and
upstream Python tests are not replaced by this probe.
