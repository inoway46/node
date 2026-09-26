# LIEF build and SEA validation

This fork-only workflow builds PR #66240 independently of the branch containing
the validation harness. It resolves `node_ref` once, records the exact Node.js SHA,
and shares source tarballs with every build job. It uses fresh source and build
directories without compiler caches or previous Node.js/LIEF objects.

## Default coverage

| Runner                        | LIEF                              | Checks                                                               |
| ----------------------------- | --------------------------------- | -------------------------------------------------------------------- |
| Windows x64, VS 2022 clang-cl | Bundled 0.17.0                    | Release Node.js, Debug LIEF archive, SEA generation/execution        |
| Windows x64, VS 2022 clang-cl | Bundled 1.0.0 from staged tarball | Same checks, generated `bcrypt.lib` linker setting                   |
| Windows x64, VS 2022 clang-cl | External shared 1.0.0             | Release LIEF and Node.js, DLL dependency, SEA generation/execution   |
| Windows x64, VS 2022 clang-cl | External shared 0.17.0            | External old-version compatibility and SEA generation/execution      |
| macOS arm64                   | External shared 1.0.0             | Release LIEF and Node.js, dylib dependency, SEA generation/execution |
| macOS x64                     | External shared 1.0.0             | Release LIEF and Node.js, dylib dependency, signed SEA generation    |

LIEF CMake enables ELF, PE, Mach-O and COFF. Android formats, JSON, logging,
extended features, runtime, bindings, examples and tests are disabled. Frozen
remains enabled and C++ exceptions remain disabled. Windows uses Visual Studio's
clang-cl and `/MT`, matching the Release Node.js executable's runtime setting.
The CMake cache, compile commands and File API replies record the effective
configuration. This exercises the same disabled-feature configuration as Node.js;
it does not claim to cover every external LIEF feature combination.

Input preparation runs the unmodified `tools/dep_updaters/update-lief.sh` on a
fresh Node.js checkout. The resulting version must be 1.0.0. It compares the result
against a second preparation from the pinned upstream archive, stages all vendor
changes with `git add -A deps/LIEF`, writes a Git tree without a commit, and
archives that tree. Every vendor file's SHA-256 must match the tarball contents,
including generated TF-PSA sources and licenses. Build jobs verify the tarball
hashes and the extracted vendor manifest again before configuring Node.js.
These are Git source archives, not `make tar` release packaging.

## SEA checks and limitations

Each Windows and arm64 macOS job builds and runs a separate SEA containing an
asset, checks `isSea()` and the LIEF version, and verifies its native library
dependencies. The existing basic and asset SEA tests must run without a skip.
The full `sea` suite and the two related parallel asset API tests then run through
the Node.js test runner, with TAP output and actual skips retained.

Windows hosted runners receive a short-lived self-signed code-signing certificate
in the runner user's certificate stores. This lets the existing SEA tests invoke
`signtool sign` and `signtool verify` without changing the tests. No private key
or certificate is uploaded. The smoke SEA also requires successful signing and
verification, so missing signing prerequisites cannot produce a green skip.

External Windows jobs use a shared LIEF DLL, available on `PATH` and copied next
to Node.js and the smoke SEA. Their success establishes external DLL compatibility;
the bundled jobs establish operation without a LIEF DLL.

macOS x64 retains the existing exclusions for issue #59553. Its default result
is explicitly `build-and-generation-only`, not an end-to-end SEA pass. Set
`execute_macos_x64_sea=true` to additionally execute the smoke SEA. Existing
status-file exclusions still apply to the suite. No frozen workaround, x64 SEA
fix, production source patch or test-status change is applied by this workflow.
External old-version coverage is specifically 0.17.0, not every 0.17.x release.

## Install and run in the fork

Install these files on a dedicated `codex/lief-validation` branch of
`inoway46/node`, rather than on the PR branch:

```text
.github/workflows/lief-validation.yml
tools/lief-validation/run.py
tools/lief-validation/README.md
```

Pushing these files to that branch starts the complete default matrix through
the `push` trigger. Results appear in the fork's Actions page. The repository
guard prevents execution in `nodejs/node`. Publication is a separate operation
from creating or checking the files locally.

For the Actions **Run workflow** UI and `gh workflow run`, GitHub requires the
workflow to exist on the fork's default branch. Once installed there, use:

```bash
gh workflow run lief-validation.yml --repo inoway46/node \
  -f node_ref=6a60729cf58ca0d694d6899fc068fcbfbf26af2e
```

The default `node_ref` is `refs/pull/66240/head`; an explicit SHA makes reruns
comparable even if the PR subsequently changes. `windows`, `macos` and
`external_old` select the jobs. If upstream's latest release has advanced beyond
1.0.0, set `use_updater=false` to prepare the pinned 1.0.0 vendor. That run records
`updater_executed=false` and does not claim to validate the updater itself.
`upload_binaries=true` adds Node.js and smoke SEA artifacts; logs and metadata are
always uploaded, including on build or test failures.

Inspect individual job summaries and `evidence-*` artifacts. A failed compiler
step is a build result, not a SEA result. Incomplete jobs are reported separately.
The workflow summary fails if preparation or any matrix job fails.

## Local checks without compiling Node.js

Use Python 3.13 or newer. The helper has no third-party Python dependency.

```bash
python tools/lief-validation/run.py --help
actionlint .github/workflows/lief-validation.yml
yamllint -c .yamllint.yaml .github/workflows/lief-validation.yml
ruff check tools/lief-validation/run.py
```

The `prepare` command writes to and stages files in its `--source` checkout.
Always pass a new isolated clone, never an active development checkout.

```bash
python tools/lief-validation/run.py prepare \
  --source /tmp/isolated-node-clone --output /tmp/new-lief-inputs
```
