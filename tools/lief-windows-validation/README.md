# Windows LIEF validation

This fork-only v2 workflow validates one resolved Node.js revision in four fresh
Windows x64 builds with Visual Studio 2022 clang-cl:

| LIEF selection         | Checks                                                                  |
| ---------------------- | ----------------------------------------------------------------------- |
| Bundled 0.17.0         | Release Node.js, Debug LIEF archive, signed SEA execution               |
| Bundled 1.0.0          | Same checks, updater-generated source archive and bcrypt linker setting |
| External shared 0.17.0 | Release LIEF and Node.js, actual DLL linkage, signed SEA execution      |
| External shared 1.0.0  | Same checks with runtime disabled                                       |

The initial run pins PR #66240 at
`534c117381397a1a598f9260f96b3d96be2e620c`. Input preparation resolves the SHA
once, runs the actual updater, compares vendor files with pinned upstream
preparation, stages the generated vendor and checks every archived file hash.
Both LIEF releases and their upstream archive hashes are pinned in `run.py`.

Signing certificates remain in `CurrentUser\My`; their public certificate is
trusted in `LocalMachine\Root` and `LocalMachine\TrustedPublisher` on the
disposable elevated hosted runner. This avoids the reproduced user Root import
hang. Preparation steps have individual timeouts and progress markers. Private
keys and certificate files are not uploaded.

Before the long Node.js build, regression checks run on both Ubuntu and Windows.
Native preflight verifies UTF-8 output, exact LF asset bytes and fixture inputs.
External jobs compile and run a small program linked to the installed LIEF DLL
using the same PATH as Node.js build tools, without copying the DLL next to it.
Bundled jobs build the generated `liblief.vcxproj` directly in Debug before
building Node.js Release. Snapshot-tool DLL dependencies are saved after the
Node.js build, including when that build fails.

Required SEA checks independently build, sign, verify and execute the smoke SEA
and copies of the existing `test/fixtures/sea/simple` and `assets` payloads.
Basic arguments, module behavior, Unicode, binary assets, NUL-containing keys,
buffer copies and Blob behavior are checked by those unchanged fixture scripts.
Only the copied configuration's output filename changes to `sea.exe`.
External jobs require LIEF DLL imports in Node.js and every generated SEA;
bundled jobs require their absence.

The existing basic/assets test scripts, the full SEA suite and two parallel
asset tests also run without edits. Their helper currently invokes
`signtool verify /pa SHA256 <file>`, treating `SHA256` as another filename.
The required basic/assets probes may be classified as blocked only when the
actual output reports that exact missing filename, a signing skip and exit zero.
Other failures or unexpected skips fail validation. A nonzero suite exit also
fails validation. All suite skips and original logs remain available.

A successful workflow establishes the required independent SEA checks. It does
not establish successful execution of existing tests that skipped because of
the known helper problem. Such results use
`passed-with-existing-test-helper-limitation` and retain the blocked test names.
Test source hashes before and after execution must match.

Push the following files to `codex/lief-windows-validation-v2` in `inoway46/node`
to start the four Windows jobs without rerunning macOS or Linux builds:

```text
.github/workflows/lief-windows-validation-v2.yml
tools/lief-windows-validation/run.py
tools/lief-windows-validation/test_harness.py
tools/lief-windows-validation/README.md
```

No production source or existing test is patched. The workflow uses no previous
Node.js/LIEF objects or compiler cache. Configure results, MSBuild projects,
external CMake configuration, native dependency inspection, test logs, TAP
results and summaries are uploaded for each Windows job.

## Evidence before v2

These results apply to the pinned revisions below, not automatically to later
Node.js changes. A green job is interpreted using its result JSON and skips.

| Configuration                     | Node.js revision | Established                                                                                                | Still unverified                                                              |
| --------------------------------- | ---------------- | ---------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Windows bundled 0.17.0 and 1.0.0  | `534c117`        | Release build, version/linkage, SEA generation, signing, signature verification and entry into the payload | Complete SEA assertions, basic/assets fixtures, SEA suite and Debug archive   |
| Windows external 0.17.0 and 1.0.0 | `534c117`        | Upstream shared LIEF build/install and Node.js configure                                                   | Complete Node.js build and SEA tests; snapshot tool failed with DLL-not-found |
| macOS arm64 external 1.0.0        | `6a60729`        | Node.js build, SEA execution, 42 tests passed, one ELF-only skip                                           | Skipped ELF-specific test is not applicable                                   |
| macOS x64 external 1.0.0          | `6a60729`        | Node.js build and SEA generation                                                                           | SEA execution excluded for existing issue 59553                               |
| macOS arm64 bundled 1.0.0         | `485ff58`        | Node.js build, SEA execution, 42 tests passed, one ELF-only skip                                           | Skipped ELF-specific test is not applicable                                   |
| Linux x64 bundled 1.0.0           | `485ff58`        | Node.js build, SEA execution, 43 tests passed                                                              | No failures or skips in the selected suite                                    |

The updater, pinned preparation, staged vendor and source tarball matched file
hashes, including generated files and licenses. The Windows bundled failures
were caused by text-mode CRLF conversion in the smoke input and an invalid
MSBuild target in the harness. External builds lacked the installed DLL in the
build-time PATH. v2 fixes these and retains strict test failure handling.

Evidence: [Windows run 36248279446][], [external macOS run 36220510661][], and
[bundled macOS/Linux run 36231412249][]. Earlier Windows prerequisite failures
established no Node.js build results.

[Windows run 36248279446]: https://github.com/inoway46/node/actions/runs/36248279446
[bundled macOS/Linux run 36231412249]: https://github.com/inoway46/node/actions/runs/36231412249
[external macOS run 36220510661]: https://github.com/inoway46/node/actions/runs/36220510661
