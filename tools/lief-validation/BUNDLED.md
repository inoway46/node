# Bundled LIEF 1.0.0 validation

`lief-bundled-validation.yml` is a separate fork-only workflow with two builds:

| Runner           | Compiler        | LIEF          | Checks                                               |
| ---------------- | --------------- | ------------- | ---------------------------------------------------- |
| macOS 15 arm64   | Apple Clang     | Bundled 1.0.0 | Clean Node.js build, signed SEA execution, SEA tests |
| Ubuntu 24.04 x64 | GCC / libstdc++ | Bundled 1.0.0 | Clean Node.js build, SEA execution, SEA tests        |

Both jobs use one resolved Node.js revision and the same Git source archive.
The push default is PR #66240 revision
`485ff581e928b82d8ba7965fa72aa78a34be5302`. The updater replaces the isolated
checkout's bundled 0.17.0 with 1.0.0 while preserving its GYP files. Preparation
checks the generated vendor against the pinned upstream archive and verifies
that all vendor files and licenses are present in the staged Git archive.

The builds use fresh directories and no compiler caches. Runtime checks require
LIEF 1.0.0, `node_shared_lief=false`, enabled SEA support, and no external LIEF
library dependency. A smoke SEA must execute and return its embedded asset.
Existing basic and asset SEA tests must execute without a skip, followed by the
SEA suite and two related parallel tests. macOS signs and verifies the smoke SEA.
Results include the source SHA, vendor hashes, compiler/configuration logs,
linkage output, actual test passes and skips, and failure logs.

## Vendor input modes

* `updater` runs the actual updater; its result must still be 1.0.0.
* `pinned` prepares 1.0.0 directly from the verified upstream archive if the
  latest release has advanced. It does not claim an updater test.
* `checked-in` requires the selected Node.js revision to already contain bundled
  1.0.0. It archives and builds that exact committed vendor without replacing
  files. Use this mode for the follow-up vendor update PR.

Early results establish that the preparatory GYP and source API changes work
with the generated 1.0.0 vendor on these two platforms. A subsequent vendor PR
must be tested again at its own revision; changed vendor patches or build files
are not covered by an earlier success.

## Run in the fork

Pushing changes to `codex/lief-bundled-validation` starts only this workflow,
independently of the existing `codex/lief-validation` run. The repository guard
permits execution only in `inoway46/node`. The workflow uses read-only repository
permissions and does not push generated vendor changes.

Once the workflow exists on the fork's default branch, manual dispatch can
select a different Node.js SHA or a `refs/pull/NUMBER/head` ref:

```bash
gh workflow run lief-bundled-validation.yml --repo inoway46/node \
  --ref codex/lief-bundled-validation \
  -f node_ref=refs/pull/NUMBER/head -f vendor_source=checked-in
```

The evidence artifacts expire after 14 days. Optional binaries expire after
7 days. Download evidence needed for a later vendor PR before it expires.
