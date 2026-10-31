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
version, arm64 architecture label, exact LIEF patch SHA, and byte-for-byte
backport diff equality against the verifier revision. The ELF inspector
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

## Measured results — 2026-10-31

The minimal #67048 reproduction passes with only the implementation changes from
5da7685 backported to Node v26.13.0. No compilation compatibility changes or
additional upstream behavioral fixes were required. The only manual patch
adaptation was placing an include in the vendored include order.

- Clean dependency commit: `d979e69ee8efbb9489ffbadd0092bc98a42776aa`.
- Built source commit: `e450c51909abb18483e5ccd7da8949b411db2d30`.
- Final verifier commit: `3357d2d41ba7a834b7c96e8a1ec8c6207e43e572`.
- [Producer run, successful build job](https://github.com/inoway46/node/actions/runs/41150179486/job/124384586984).
- [Final verification run, all three verifiers passed and build skipped](https://github.com/inoway46/node/actions/runs/41157496904).
- [Reusable binary artifact](https://github.com/inoway46/node/actions/runs/41150179486/artifacts/13025437501).

| Actual page size | Kernel | Patched Node / SEA generation exit | Stored patched SEA exit | Guest/host regenerated SEA exit | Official SEA exit | Patched ELF checks |
| --- | --- | --- | --- | --- | --- | --- |
| 4096 | 7.0.0-1017-azure | 0 / 0 | 0 | 0 | 0 | PASS |
| 16384 | 6.12.113+deb13-arm64-16k | 0 / 0 | 0 | 0 | 139 | PASS |
| 65536 | 6.8.0-147-generic-64k | 0 / 0 | 0 | 0 | 139 | PASS |

Every successful patched SEA printed `hello from sea v26.13.0`. Official SEA
also printed this on 4 KiB; its success was recorded. The large-page guests use
real Debian/Ubuntu distribution kernels with Ubuntu runner userspace libraries
copied into the existing minimal initramfs. They are not full distribution VMs.
Guest-side regenerated SEA was independently inspected with readelf and the
JavaScript ELF inspector before execution.

Independent inspection of the downloaded producer artifact confirmed:

- Patched Node and stored patched SEA have congruent PT_LOAD address/file offsets
  and no shared virtual pages at 4096, 16384, or 65536 bytes.
- Official SEA fails both 16/64 KiB checks: LOAD 7 has incongruent address/file
  offsets, and LOAD 5/6 share a virtual page. It passes at 4096 bytes.
- The patched SEA still has added LOADs whose p_align is 0x1000. Their actual
  addresses/offsets and separation satisfy 64 KiB mapping requirements. No extra
  alignment-field change from the earlier diagnostic candidate was applied.
- All packaged file SHA256 checks and the archive SHA256 check passed after
  download. Executable permission remained set after tar extraction.

`products.tar.gz` SHA256:

```text
b191d117517cbf050fc82044e36ab1f5d554dc2c4e1b400fc46a8c6f15b6cc62
```

The binary artifact is 237,717,380 bytes including its GitHub ZIP wrapper. It
expires on **2026-11-30 at 01:52:40 UTC**, unless deleted earlier. The producer
also retains `node-v26.13.0-linux-arm64-lief-5da7685-build-logs`. The final verifier
run retains three evidence artifacts with the same prefix and suffixes
`-4096-evidence`, `-16384-evidence`, and `-65536-evidence`; their expiry is also
2026-11-30. They contain readelf output, layout JSON, kernel provenance, SHA256
manifests, serial console execution/generation logs, exit codes and failed
control execve traces, as appropriate to each environment.

A concrete reuse command for these measured products is:

```sh
gh workflow run sea-lief-backport.yml -R inoway46/node \
  --ref codex/sea-v26.13.0-lief-5da7685 \
  -f mode=verify-only -f source_run_id=41150179486
```

### Failed attempts and their diagnosis

- Run 41149580721 stopped before configure because the fork lacks the upstream
  v26.13.0 tag. Using the immutable base commit fixed the provenance command.
- Run 41149802467 was canceled while building to match the existing probe's
  Rust 1.88 and four-job settings; it is not evidence of a LIEF compilation failure.
- Run 41150001380 intentionally requested a missing binary artifact. Verification
  failed with `Artifact not found`, and build was skipped: no implicit rebuild.
- The producer run's original 16/64 KiB verifiers stopped on the expected official
  ELF failure because Actions bash enables errexit. Logs show patched ELF checks
  passed, then the negative inspector stopped the step before QEMU. The corrected
  collector explicitly records negative failures and defers positive failure
  checks until after execution. Final run 41157496904 used the exact same binary
  artifact, with no rebuild, and passed all runtime and ELF checks.

### Scope of the conclusion and remaining PR work

These results establish sufficiency for the requested minimal SEA reproduction
with this Node source build and all three kernel page sizes. The official control
and source build have different link layouts; this is not an identical-build
unpatched/patched causal comparison. Broader SEA features and the full Node CI
suite have not been tested. Before proposing a Node core PR, add an appropriate
Node regression test that checks supported larger page sizes even on a 4 KiB
host, run the required Node CI/SEA suite, and review the backport with maintainers.
An official-release-equivalent build and an otherwise identical unpatched source
build would further strengthen release-wide conclusions. No upstream PR or issue
comment was created.
