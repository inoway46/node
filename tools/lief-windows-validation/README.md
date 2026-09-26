# Windows LIEF validation

This fork-only workflow validates one resolved Node.js revision in four fresh
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

Push the following files to `codex/lief-windows-validation` in `inoway46/node`
to start the four Windows jobs without rerunning macOS or Linux builds:

```text
.github/workflows/lief-windows-validation.yml
tools/lief-windows-validation/run.py
tools/lief-windows-validation/README.md
```

No production source or existing test is patched. The workflow uses no previous
Node.js/LIEF objects or compiler cache. Configure results, MSBuild projects,
external CMake configuration, native dependency inspection, test logs, TAP
results and summaries are uploaded for each Windows job.
