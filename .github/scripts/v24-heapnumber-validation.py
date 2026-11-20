# Fork-only validation; do not include this script in the upstream PR.
import json
import pathlib
import re
import resource
import shlex
import signal
import subprocess
import sys

TESTS = [
    'regress-547819997',
    'regress-41497204',
    'escape-analysis-context',
    'escape-loop-inline-call',
    'regress-328676392',
    'regress-328680228',
    'regress-328846303',
    'regress-328868985',
    'regress-329474361',
    'regress-330095905-3',
    'inline-fresh-parent-deopt-frame',
    'eager-deopt-in-inline',
    'lazy-deopt-with-onstack-activation',
    'lazy-deopt-without-onstack-activation',
    'spill-double',
    'store-oddball-to-double-elements',
]


def run_tests(node_root, variant, revision, output):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    root = node_root / 'deps/v8'
    binary = node_root / 'out/Release/d8'
    output.mkdir(parents=True, exist_ok=True)
    actual = subprocess.check_output(
        ['git', '-C', str(node_root), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != revision:
        raise RuntimeError(f'Unexpected revision: {actual}')
    results = []
    for name in TESTS:
        path = pathlib.Path('test/mjsunit/maglev') / (name + '.js')
        source = (root / path).read_text()
        flags = [arg for line in re.findall(r'^//\s+Flags:(.*)$', source, re.M)
                 for arg in shlex.split(line)]
        files = [arg for line in re.findall(r'^//\s+Files:(.*)$', source, re.M)
                 for arg in shlex.split(line)]
        command = [str(binary), '--test', *flags, *files,
                   'test/mjsunit/mjsunit.js', str(path)]
        try:
            completed = subprocess.run(command, cwd=root, capture_output=True,
                                       text=True, timeout=120)
            code = completed.returncode
            log = completed.stdout + completed.stderr
        except subprocess.TimeoutExpired as exc:
            code = None
            log = 'TIMEOUT\n' + (exc.stdout or b'').decode(errors='replace')
            log += (exc.stderr or b'').decode(errors='replace')
        unknown_flag = re.search(
            r'(unknown|unrecognized) (command.line )?(flag|option)', log, re.I)
        crash_signals = {-signal.SIGABRT, -signal.SIGTRAP, -signal.SIGILL}
        unreachable = (code in crash_signals and
                       'unreachable code' in log.lower())
        passed = code == 0 and not unknown_flag
        expected_failure = variant == 'before' and unreachable and not unknown_flag
        acceptable = passed or expected_failure
        if variant == 'before' and name == 'regress-547819997':
            acceptable = bool(expected_failure)
        status = ('PASS' if passed else 'EXPECTED CRASH' if expected_failure
                  else 'UNEXPECTED FAILURE')
        record = dict(test=name, returncode=code, status=status,
                      acceptable=bool(acceptable), command=command)
        results.append(record)
        (output / (name + '.log')).write_text(
            '$ ' + shlex.join(command) + '\n' + log)
        print(f'{variant}: {name}: {status} (exit {code})', flush=True)
    good = all(result['acceptable'] for result in results)
    document = dict(variant=variant, revision=actual, accepted=good,
                    results=results)
    (output / 'results.json').write_text(json.dumps(document, indent=2) + '\n')
    passed = sum(result['status'] == 'PASS' for result in results)
    crashes = sum(result['status'] == 'EXPECTED CRASH' for result in results)
    summary = [f'## {variant}: Linux x64', '', f'Revision: `{actual}`', '',
               f'{passed}/{len(results)} passed; {crashes} expected crashes.', '',
               '| Existing mjsunit test | Result | Exit code |',
               '| --- | --- | --- |']
    summary.extend(f"| `{r['test']}` | {r['status']} | {r['returncode']} |"
                   for r in results)
    summary += ['', 'Tests use d8 built from the exact revision above, the '
                'original mjsunit harness, and each test\'s declared flags.', '',
                'The before job requires regress-547819997 to abort with '
                'unreachable code. The after job requires all 16 tests to pass.', '',
                'This is a focused test selection, not the complete V8 CI suite.', '']
    (output / 'summary.md').write_text('\n'.join(summary))
    return 0 if good else 1


if __name__ == '__main__':
    sys.exit(run_tests(pathlib.Path(sys.argv[1]).resolve(), sys.argv[2],
                       sys.argv[3], pathlib.Path(sys.argv[4]).resolve()))
